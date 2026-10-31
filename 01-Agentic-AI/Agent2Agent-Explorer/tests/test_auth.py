"""Auth tests: bearer-protected local A2A server; token handling + redaction."""
import asyncio
import logging
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, HTTPAuthSecurityScheme, Part, SecurityScheme

from remote_agents.card_validator import ValidatedCard
from remote_agents.remote_client import RemoteAuthError, send_task

PORT = 9802
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "sekrit-token-12345"

CARD = AgentCard(
    name="Auth Agent",
    description="requires bearer auth",
    version="0.0.1",
    supported_interfaces=[AgentInterface(url=f"{BASE}/", protocol_binding="JSONRPC", protocol_version="1.0")],
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[AgentSkill(id="echo", name="Echo", description="echoes", tags=["t"])],
    security_schemes={"bearer": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer"))},
)


class EchoExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        await updater.complete(updater.new_agent_message([Part(text=f"echo: {context.get_user_input()}")]))

    async def cancel(self, context, event_queue):
        pass


@pytest.fixture(scope="module")
def server():
    app = FastAPI()

    @app.middleware("http")
    async def require_bearer(request: Request, call_next):
        # the card itself stays public; the A2A endpoint requires the token
        if request.url.path != "/.well-known/agent-card.json":
            if request.headers.get("authorization") != f"Bearer {TOKEN}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    handler = DefaultRequestHandler(agent_executor=EchoExecutor(), task_store=InMemoryTaskStore(), agent_card=CARD)
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(CARD),
        jsonrpc_routes=create_jsonrpc_routes(handler, "/"),
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            httpx.get(f"{BASE}/.well-known/agent-card.json", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("auth test server did not start")
    yield BASE
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def vc(server) -> ValidatedCard:
    return ValidatedCard(card=CARD, source_url=f"{BASE}/.well-known/agent-card.json")


@pytest.mark.asyncio
async def test_valid_token_completes(vc):
    result = await send_task(vc, "hello", allow_local=True, timeout=30, bearer_token=TOKEN)
    assert result.state == "COMPLETED"
    assert any("echo: hello" in t for t in result.texts)


@pytest.mark.asyncio
async def test_missing_token_clear_error(vc):
    with pytest.raises(RemoteAuthError, match="unauthorized.*bearer|bearer.*unauthorized|unauthorized"):
        await send_task(vc, "hello", allow_local=True, timeout=30)


@pytest.mark.asyncio
async def test_invalid_token_clear_error(vc):
    with pytest.raises(RemoteAuthError, match="bearer token"):
        await send_task(vc, "hello", allow_local=True, timeout=30, bearer_token="wrong-token")


@pytest.mark.asyncio
async def test_token_never_logged(vc, caplog, capsys):
    with caplog.at_level(logging.DEBUG):
        result = await send_task(vc, "hello", allow_local=True, timeout=30, bearer_token=TOKEN)
    assert result.state == "COMPLETED"
    assert TOKEN not in caplog.text
    captured = capsys.readouterr()
    assert TOKEN not in captured.out and TOKEN not in captured.err
    assert TOKEN not in result.display()


@pytest.mark.asyncio
async def test_credentials_not_reused_across_calls(vc):
    # a token supplied to one call must not leak into the next (per-agent isolation)
    assert (await send_task(vc, "a", allow_local=True, timeout=30, bearer_token=TOKEN)).state == "COMPLETED"
    with pytest.raises(RemoteAuthError):
        await send_task(vc, "b", allow_local=True, timeout=30)
