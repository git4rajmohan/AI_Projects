"""Agent B (worker): local A2A server that answers questions via Ollama Cloud.

Run: .venv\\Scripts\\python.exe worker.py
"""
import asyncio

import uvicorn
from fastapi import FastAPI

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part
from a2a.utils import TransportProtocol
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT

from smoke_test import ask  # ponytail: reuse the already-working Ollama Cloud call

HOST, PORT = "127.0.0.1", 9999

CARD = AgentCard(
    name="Worker Agent",
    description="Answers text questions using Ollama Cloud.",
    version="0.1.0",
    supported_interfaces=[
        AgentInterface(
            url=f"http://{HOST}:{PORT}/",
            protocol_binding=TransportProtocol.JSONRPC,
            protocol_version=PROTOCOL_VERSION_CURRENT,
        )
    ],
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="qa",
            name="Question Answering",
            description="Answers a text question with the configured LLM.",
            tags=["qa"],
        )
    ],
)


class WorkerExecutor(AgentExecutor):
    """Runs one task: sends the user text to Ollama Cloud, completes with the answer."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        try:
            # ponytail: sync ask() in a thread; swap to AsyncClient if concurrency matters
            answer = await asyncio.to_thread(ask, context.get_user_input())
            await updater.complete(updater.new_agent_message([Part(text=answer)]))
        except Exception as exc:
            await updater.failed(updater.new_agent_message([Part(text=f"error: {exc}")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def build_app() -> FastAPI:
    """FastAPI app serving the agent card and JSON-RPC A2A endpoint."""
    handler = DefaultRequestHandler(
        agent_executor=WorkerExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=CARD,
    )
    app = FastAPI()
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(CARD),
        jsonrpc_routes=create_jsonrpc_routes(handler, "/"),
    )
    return app


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
