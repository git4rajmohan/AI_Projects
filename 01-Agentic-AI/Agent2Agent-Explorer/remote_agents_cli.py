"""Remote Agents page (CLI) — screens A-E from instructions §11.

Usage (all via .venv\\Scripts\\python.exe remote_agents_cli.py ...):
  search <query>            Screen A/B: search the public registry
  discover <card-url>       Screen A/C: fetch card, show details + staged validation
  save <card-url>           Screen E: validate and save agent metadata (SQLite)
  list                      Screen E: saved agents
  trust <id> | untrust <id> Screen E: mark trusted/untrusted
  refresh <id>              Screen E: refetch + revalidate a saved agent's card
  remove <id>               Screen E: delete a saved agent (and its history)
  task <id|card-url> <text> Screen D: send an A2A task, show status/result/task ID
  history <id>              Screen E: task history for a saved agent

Bearer tokens are read from the A2A_BEARER_TOKEN env var — never from argv,
never persisted.
"""
import argparse
import asyncio
import os
import sys

from directories.registry_provider import A2ARegistryProvider, resolve_page_url
from remote_agents.agent_store import AgentStore
from remote_agents.card_fetcher import CardFetchError, fetch_card_json
from remote_agents.card_validator import CardValidationError, ValidatedCard, summarize_card, validate_card
from remote_agents.endpoint_validator import check_endpoint
from remote_agents.remote_client import RemoteAuthError, send_task
from remote_agents.url_safety import UnsafeUrlError

DB_PATH = "agents.db"


def load_card(url: str) -> ValidatedCard:
    # registry detail-page URLs (https://a2aregistry.org/agents/<id>/) resolve to the real card
    try:
        return validate_card(fetch_card_json(url), url)
    except CardFetchError:
        card_url = resolve_page_url(url)
        if not card_url:
            raise
        return validate_card(fetch_card_json(card_url), card_url)


def resolve_card_url(store: AgentStore, ref: str) -> str:
    """`ref` is a saved agent id or a card URL."""
    if ref.isdigit():
        agent = store.get_agent(int(ref))
        if not agent:
            sys.exit(f"ERROR: no saved agent with id {ref}")
        return agent["agent_card_url"]
    return ref


def cmd_search(args, store):
    from directories.registry_provider import A2ARegistryProvider

    candidates = A2ARegistryProvider().search(" ".join(args.query))
    if not candidates:
        print("No matching agents. You can paste an Agent Card URL instead (discover <url>).")
        return
    for c in candidates:
        print(c.display(), end="\n\n")


def cmd_discover(args, store):
    vc = load_card(args.url)
    print(summarize_card(vc), check_endpoint(vc).display(), sep="\n\n")


def cmd_save(args, store):
    vc = load_card(args.url)
    report = check_endpoint(vc)
    agent_id = store.save_agent(vc)
    print(f"Saved agent #{agent_id}: {vc.card.name}")
    print(report.display())
    if not report.task_ready:
        print("NOTE: endpoint not validated as task-ready yet.")


def cmd_list(args, store):
    agents = store.list_agents()
    if not agents:
        print("No saved agents. Use: save <card-url>")
    for a in agents:
        trust = "trusted" if a["trusted"] else "untrusted"
        print(f"#{a['id']} {a['name']} [{trust}] auth={a['auth_scheme'] or 'none'}")
        print(f"    endpoint: {a['service_endpoint']}  last validated: {a['last_validated_at']}")


def cmd_trust(args, store, trusted=True):
    store.set_trusted(args.id, trusted)
    print(f"Agent #{args.id} marked {'trusted' if trusted else 'untrusted'}.")


def cmd_refresh(args, store):
    agent = store.get_agent(args.id)
    if not agent:
        sys.exit(f"ERROR: no saved agent with id {args.id}")
    vc = load_card(agent["agent_card_url"])
    store.save_agent(vc)
    print(f"Refreshed agent #{args.id}: {vc.card.name}")
    print(check_endpoint(vc).display())


def cmd_task(args, store):
    url = resolve_card_url(store, args.agent)
    vc = load_card(url)
    token = os.getenv("A2A_BEARER_TOKEN") or None
    text = " ".join(args.text)
    print(f"Sending task to '{vc.card.name}' ...")
    result = asyncio.run(send_task(vc, text, bearer_token=token, progress=lambda s: print(f"  status: {s}")))
    print(result.display())
    row = next((a for a in store.list_agents() if a["agent_card_url"] == url), None)
    if row:
        store.record_task(row["id"], text, result)


def cmd_history(args, store):
    rows = store.task_history(args.id)
    if not rows:
        print("No task history.")
    for h in rows:
        print(f"{h['completed_at']}  task {h['task_id'] or '?'}  {h['task_state']}")
        if h["result_summary"]:
            print(f"    {h['result_summary'][:120]}")


def cmd_remove(args, store):
    if store.delete_agent(args.id):
        print(f"Removed agent #{args.id} and its task history.")
    else:
        sys.exit(f"ERROR: no saved agent with id {args.id}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="remote_agents_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("search").add_argument("query", nargs="+")
    sub.add_parser("discover").add_argument("url")
    sub.add_parser("save").add_argument("url")
    sub.add_parser("list")
    sub.add_parser("trust").add_argument("id", type=int)
    sub.add_parser("untrust").add_argument("id", type=int)
    sub.add_parser("refresh").add_argument("id", type=int)
    sub.add_parser("remove").add_argument("id", type=int)
    p_task = sub.add_parser("task")
    p_task.add_argument("agent", help="saved agent id or Agent Card URL")
    p_task.add_argument("text", nargs="+")
    sub.add_parser("history").add_argument("id", type=int)
    args = parser.parse_args(argv)

    store = AgentStore(DB_PATH)
    handlers = {
        "search": cmd_search, "discover": cmd_discover, "save": cmd_save, "list": cmd_list,
        "trust": cmd_trust, "untrust": lambda a, s: cmd_trust(a, s, trusted=False),
        "refresh": cmd_refresh, "task": cmd_task, "history": cmd_history, "remove": cmd_remove,
    }
    try:
        handlers[args.cmd](args, store)
    except (UnsafeUrlError, CardFetchError, CardValidationError, RemoteAuthError) as exc:
        sys.exit(f"ERROR: {exc}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
