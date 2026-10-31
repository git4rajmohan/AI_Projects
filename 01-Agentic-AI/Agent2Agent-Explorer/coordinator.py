"""Agent A (coordinator): delegates tasks to the local worker or saved remote agents.

Run: .venv\\Scripts\\python.exe coordinator.py "your question"           (local worker)
     .venv\\Scripts\\python.exe coordinator.py remote "your question"    (saved remote agent)
"""
import asyncio
import json
import re
import sys
from dataclasses import dataclass

from a2a.client import create_client
from a2a.helpers import get_stream_response_text, new_text_message
from a2a.types import Role, SendMessageRequest

from remote_agents.agent_store import AgentStore
from remote_agents.card_fetcher import fetch_card_json
from remote_agents.card_validator import validate_card
from remote_agents.remote_client import TaskResult, send_task

WORKER_URL = "http://127.0.0.1:9999"


async def delegate(text: str, url: str = WORKER_URL) -> str:
    """Resolve the agent card at `url`, send `text` as a task, return the final answer."""
    async with await create_client(url) as client:
        request = SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))
        chunks = [t async for r in client.send_message(request) if (t := get_stream_response_text(r))]
        return chunks[-1] if chunks else ""


# --- remote delegation (deterministic routing, user confirmation, attribution) ---

@dataclass
class Route:
    agent_id: int
    agent_name: str
    card_url: str
    skill_id: str
    skill_name: str


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def match_route(store: AgentStore, task_text: str) -> Route | None:
    """Pick the saved agent whose advertised skill best matches the request.

    Deterministic word-overlap scoring — the LLM never chooses or invents URLs.
    """
    # ponytail: bag-of-words overlap; swap in LLM-assisted routing later if needed
    request = _words(task_text)
    best, best_score = None, 0
    for agent in store.list_agents():
        for skill in json.loads(agent["skills_json"] or "[]"):
            haystack = _words(f"{agent['name']} {skill.get('name', '')} {skill.get('description', '')}")
            score = len(request & haystack)
            if score > best_score:
                best_score = score
                best = Route(agent["id"], agent["name"], agent["agent_card_url"], skill["id"], skill["name"])
    return best


async def delegate_remote(
    store: AgentStore,
    task_text: str,
    *,
    confirm,
    bearer_token: str | None = None,
    allow_local: bool | None = None,
    timeout: float | None = None,
) -> TaskResult | None:
    """Route to a saved agent, require confirmation, send over A2A, record history.

    Returns None when no agent matches or the user declines.
    """
    route = match_route(store, task_text)
    if route is None:
        return None
    if not confirm(f"Send task to '{route.agent_name}' using skill '{route.skill_name}' ({route.card_url})?"):
        return None
    vc = validate_card(fetch_card_json(route.card_url, allow_local=allow_local), route.card_url)
    result = await send_task(vc, task_text, bearer_token=bearer_token, allow_local=allow_local, timeout=timeout)
    store.record_task(route.agent_id, task_text, result)
    return result


def present(result: TaskResult) -> str:
    """Attributed, verbatim presentation. Remote output is untrusted data:
    never executed, never parsed as instructions, never allowed to alter config."""
    kind = "message-only reply (no task ID)" if result.message_only() else f"Task ID:       {result.task_id or '?'}"
    lines = [
        f"Remote agent:  {result.agent_name}",
        kind,
        f"State:         {result.state}",
    ]
    if result.is_paid_offer():
        lines.append("NOTE: this agent offered a PAID tool; nothing was charged or sent.")
    lines += ["--- remote output (untrusted, displayed verbatim) ---"]
    lines += result.texts
    lines += [f"structured data: {d!r}" for d in result.data]
    lines += [f"artifact: {a!r} (not downloaded)" for a in result.artifacts]
    return "\n".join(lines)


async def delegate_parallel(
    store: AgentStore,
    agent_ids: list[int],
    task_text: str,
    *,
    allow_local: bool | None = None,
    timeout: float | None = None,
    bearer_token: str | None = None,
) -> list[TaskResult]:
    """Send the same task to several explicitly chosen saved agents concurrently.

    Explicit selection only — no automatic fan-out. Results keep per-agent attribution.
    """

    async def one(agent_id: int) -> TaskResult:
        agent = store.get_agent(agent_id)
        if not agent:
            raise ValueError(f"no saved agent with id {agent_id}")
        url = agent["agent_card_url"]
        vc = validate_card(fetch_card_json(url, allow_local=allow_local), url)
        result = await send_task(vc, task_text, allow_local=allow_local, timeout=timeout, bearer_token=bearer_token)
        store.record_task(agent_id, task_text, result)
        return result

    return list(await asyncio.gather(*(one(a) for a in agent_ids)))


def present_many(results: list[TaskResult]) -> str:
    """Combined view of parallel results, each block clearly attributed."""
    return "\n\n".join(present(r) for r in results)


def _cli_confirm(message: str) -> bool:
    return input(f"{message} [y/N] ").strip().lower().startswith("y")


if __name__ == "__main__":
    if sys.argv[1:2] == ["remote"]:
        question = " ".join(sys.argv[2:]) or "echo hello"
        store = AgentStore("agents.db")
        try:
            outcome = asyncio.run(delegate_remote(store, question, confirm=_cli_confirm))
        finally:
            store.close()
        print(present(outcome) if outcome else "No matching saved agent, or canceled.")
    elif sys.argv[1:2] == ["parallel"]:
        # usage: coordinator.py parallel <id> <id> [...] "question"
        ids = [int(a) for a in sys.argv[2:] if a.isdigit()]
        question = " ".join(a for a in sys.argv[2:] if not a.isdigit())
        if len(ids) < 2 or not question:
            sys.exit("usage: coordinator.py parallel <id> <id> [...] <question>")
        store = AgentStore("agents.db")
        try:
            outcomes = asyncio.run(delegate_parallel(store, ids, question))
        finally:
            store.close()
        print(present_many(outcomes))
    else:
        question = " ".join(sys.argv[1:]) or "Reply with exactly one word: pong"
        print(f"[worker agent] {asyncio.run(delegate(question))}")
