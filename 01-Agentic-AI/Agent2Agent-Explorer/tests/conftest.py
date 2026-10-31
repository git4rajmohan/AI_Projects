"""Shared fixtures: a scripted local A2A test server (same SDK, no LLM).

Executor behavior is keyed by task text: fail / data / hang / echo.
"""
import asyncio
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from a2a.helpers import new_data_part, new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part

from remote_agents.card_validator import ValidatedCard

SCRIPTED_PORT = 9801
SCRIPTED_BASE = f"http://127.0.0.1:{SCRIPTED_PORT}"
SCRIPTED_CARD_URL = f"{SCRIPTED_BASE}/.well-known/agent-card.json"

SCRIPTED_CARD = AgentCard(
    name="Test Agent",
    description="scripted test agent",
    version="0.0.1",
    supported_interfaces=[
        AgentInterface(url=f"{SCRIPTED_BASE}/", protocol_binding="JSONRPC", protocol_version="1.0")
    ],
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[AgentSkill(id="echo", name="Echo", description="echoes text back", tags=["t"])],
)


class ScriptedExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        text = context.get_user_input()
        if "hang" in text:
            await asyncio.sleep(60)
        elif "fail" in text:
            await updater.failed(updater.new_agent_message([Part(text="scripted failure")]))
        elif "data" in text:
            await updater.add_artifact([new_data_part({"answer": 42})], name="result-data")
            await updater.complete(updater.new_agent_message([Part(text="data attached")]))
        else:
            await updater.complete(updater.new_agent_message([Part(text=f"echo: {text}")]))

    async def cancel(self, context, event_queue):
        task = context.current_task
        await TaskUpdater(event_queue, task.id, task.context_id).cancel()


def run_a2a_server(card: AgentCard, executor: AgentExecutor, port: int, app: FastAPI | None = None):
    """Start a uvicorn A2A server in a daemon thread; returns (server, thread)."""
    app = app or FastAPI()
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card)
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, "/"),
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("test server did not start")
    return srv, thread


SECOND_PORT = 9803
SECOND_BASE = f"http://127.0.0.1:{SECOND_PORT}"
SECOND_CARD_URL = f"{SECOND_BASE}/.well-known/agent-card.json"

SECOND_CARD = AgentCard(
    name="Second Agent",
    description="independent second scripted agent",
    version="0.0.1",
    supported_interfaces=[
        AgentInterface(url=f"{SECOND_BASE}/", protocol_binding="JSONRPC", protocol_version="1.0")
    ],
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[AgentSkill(id="echo2", name="Echo Two", description="also echoes text", tags=["t"])],
)


@pytest.fixture(scope="session")
def scripted_server():
    srv, thread = run_a2a_server(SCRIPTED_CARD, ScriptedExecutor(), SCRIPTED_PORT)
    yield SCRIPTED_BASE
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def second_server():
    srv, thread = run_a2a_server(SECOND_CARD, ScriptedExecutor(), SECOND_PORT)
    yield SECOND_BASE
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def second_vc(second_server) -> ValidatedCard:
    return ValidatedCard(card=SECOND_CARD, source_url=SECOND_CARD_URL)


@pytest.fixture
def scripted_vc(scripted_server) -> ValidatedCard:
    return ValidatedCard(card=SCRIPTED_CARD, source_url=SCRIPTED_CARD_URL)
