"""Send a task to a validated remote A2A agent and track its lifecycle.

Wraps the installed a2a-sdk 1.3.0 client: uses the card's advertised
endpoint, explicit timeouts, streaming with a polling fallback. Results keep
text, structured data, and artifact metadata separate; artifacts are never
auto-downloaded.
"""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from a2a.client import ClientConfig, ClientFactory
from a2a.helpers import get_data_parts, get_message_text, get_text_parts, new_text_message
from a2a.types import CancelTaskRequest, GetTaskRequest, Role, SendMessageRequest, Task, TaskState
from a2a.utils import TransportProtocol

from remote_agents.card_validator import ValidatedCard
from remote_agents.config import settings
from remote_agents.endpoint_validator import select_interface
from remote_agents.url_safety import validate_url

TERMINAL = {"COMPLETED", "FAILED", "CANCELED", "REJECTED"}


def _state_name(state: int) -> str:
    return TaskState.Name(state).removeprefix("TASK_STATE_")


@dataclass
class TaskResult:
    """Outcome of one remote task, attributed to the agent that produced it."""

    agent_name: str
    state: str = "UNKNOWN"
    task_id: str = ""
    context_id: str = ""
    texts: list[str] = field(default_factory=list)
    data: list = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)

    def message_only(self) -> bool:
        """Agent replied without creating a Task object, so there is no task ID."""
        return self.task_id == "" and self.state in ("UNKNOWN", "COMPLETED")

    def is_paid_offer(self) -> list | None:
        """Structured data blocks that offer a paid tool (x402-style). None if unpaid.

        Detection is metadata-only (intent/price fields); the offer is never executed.
        """
        offers = []
        for d in self.data:
            if isinstance(d, dict) and str(d.get("intent", "")).lower() in ("paid_tool", "payment_required"):
                offers.append(d)
        return offers or None

    def display(self) -> str:
        kind = "message-only reply (no task ID)" if self.message_only() else f"task {self.task_id or '?'}"
        lines = [f"[{self.agent_name}] {kind}: {self.state}"]
        if self.is_paid_offer():
            lines.append("NOTE: this agent offered a PAID tool; nothing was charged or sent.")
        lines += self.texts
        lines += [f"structured data: {d!r}" for d in self.data]
        lines += [f"artifact: {a!r} (not downloaded)" for a in self.artifacts]
        return "\n".join(lines)


def _absorb_task(task: Task, result: TaskResult) -> None:
    result.task_id = task.id
    result.context_id = task.context_id
    result.state = _state_name(task.status.state)
    for artifact in task.artifacts:
        result.data += get_data_parts(artifact.parts)
        result.artifacts.append(
            {
                "artifact_id": artifact.artifact_id,
                "name": artifact.name,
                "description": artifact.description,
                "media_types": [p.media_type for p in artifact.parts if p.media_type],
            }
        )
    if task.status.HasField("message"):
        if text := get_message_text(task.status.message):
            result.texts.append(text)
        result.data += get_data_parts(task.status.message.parts)


def _make_client(vc: ValidatedCard, *, allow_local: bool | None = None, bearer_token: str | None = None):
    """SSRF-check the advertised endpoint, then build an SDK client for the card."""
    iface = select_interface(vc)
    validate_url(iface.url, allow_local=allow_local)
    httpx_client = None
    if bearer_token:
        # ponytail: per-call client = per-agent credential isolation; token lives only
        # in this header, is never logged, and follow_redirects=False stops cross-origin leaks
        httpx_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {bearer_token}"},
            follow_redirects=False,
            timeout=settings.default_timeout,
        )
    config = ClientConfig(
        streaming=bool(vc.card.capabilities.streaming),
        polling=True,
        httpx_client=httpx_client,
        supported_protocol_bindings=[TransportProtocol.JSONRPC, TransportProtocol.HTTP_JSON],
    )
    return ClientFactory(config).create(vc.card)


async def send_task(
    vc: ValidatedCard,
    text: str,
    *,
    timeout: float | None = None,
    allow_local: bool | None = None,
    bearer_token: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> TaskResult:
    """Submit `text` as a task; return a TaskResult (state TIMEOUT if it never finishes).

    `progress` (if given) is called with each new lifecycle state as it arrives.
    Raises RemoteAuthError with a clear message when the agent rejects credentials.
    """
    timeout = settings.task_timeout if timeout is None else timeout
    result = TaskResult(agent_name=vc.card.name)
    request = SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))

    last_state = result.state

    def notify():
        nonlocal last_state
        if progress and result.state != last_state:
            last_state = result.state
            progress(result.state)

    try:
        async with asyncio.timeout(timeout):
            async with _make_client(vc, allow_local=allow_local, bearer_token=bearer_token) as client:
                async for event in client.send_message(request):
                    which = event.WhichOneof("payload")
                    if which == "task":
                        _absorb_task(event.task, result)
                    elif which == "message":
                        result.texts += get_text_parts(event.message.parts)
                        result.data += get_data_parts(event.message.parts)
                    elif which == "artifact_update":
                        artifact = event.artifact_update.artifact
                        result.data += get_data_parts(artifact.parts)
                        result.artifacts.append(
                            {
                                "artifact_id": artifact.artifact_id,
                                "name": artifact.name,
                                "description": artifact.description,
                                "media_types": [p.media_type for p in artifact.parts if p.media_type],
                            }
                        )
                    elif which == "status_update":
                        result.state = _state_name(event.status_update.status.state)
                        if event.status_update.status.HasField("message"):
                            if t := get_message_text(event.status_update.status.message):
                                result.texts.append(t)
                    notify()
                # stream ended non-terminal -> poll by task ID
                while result.task_id and result.state not in TERMINAL:
                    await asyncio.sleep(settings.poll_interval)
                    task = await client.get_task(GetTaskRequest(id=result.task_id))
                    result.texts, result.data, result.artifacts = [], [], []
                    _absorb_task(task, result)
                    notify()
                # message-only reply (no Task object) is a completed exchange
                if result.state == "UNKNOWN" and (result.texts or result.data):
                    result.state = "COMPLETED"
                notify()
    except TimeoutError:
        result.state = "TIMEOUT"
    except Exception as exc:
        if any(code in str(exc) for code in ("401", "403", "Unauthorized", "Forbidden")):
            scheme = ", ".join(vc.card.security_schemes) or "unknown scheme"
            raise RemoteAuthError(
                f"agent '{vc.card.name}' rejected the request as unauthorized; "
                f"it advertises authentication: {scheme}. Check or supply a bearer token."
            ) from exc
        raise
    return result


class RemoteAuthError(Exception):
    """Remote agent rejected credentials (missing or invalid)."""


async def cancel_task(
    vc: ValidatedCard,
    task_id: str,
    *,
    allow_local: bool | None = None,
    bearer_token: str | None = None,
) -> str:
    """Request cancellation; returns the resulting task state."""
    async with _make_client(vc, allow_local=allow_local, bearer_token=bearer_token) as client:
        task = await client.cancel_task(CancelTaskRequest(id=task_id))
        return _state_name(task.status.state)
