"""API routes for agents.

GET /api/agents — List agents from a plan
POST /api/agents/execute — Execute a single agent (for testing)
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.factory.agent_factory import FactoryError, get_factory
from app.factory.context import AgentContext
from app.factory.runtime import AgentRuntime, create_runtime
from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec

router = APIRouter()
logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    """Agent response."""

    id: str
    name: str
    description: str = ""
    goal: str
    tools: list[str] = []
    dependencies: list[str] = []
    requires_human_approval: bool = False
    max_iterations: int = 5
    max_tool_calls: int = 20
    timeout_seconds: int = 300


class ExecuteAgentRequest(BaseModel):
    """Request to execute a single agent directly.

    Either provide a full AgentSpec, or provide a plan_id + agent_id
    to execute an agent from a stored plan.
    """

    agent_spec: AgentSpec | None = None
    intent: str = ""
    inputs: dict = {}
    working_memory: dict = {}


@router.get("")
async def list_agents():
    """List agents from all plans in the database.

    Note: agents are dynamically created per-plan, so this returns
    agents from stored plans. In the future, this may also show
    currently running agents.
    """
    from sqlalchemy import select

    from app.db.database import get_db_session
    from app.models.plan import PlanModel

    session = await get_db_session()
    try:
        result = await session.execute(select(PlanModel))
        plans = result.scalars().all()

        agents: list[AgentResponse] = []
        for plan in plans:
            plan_data = plan.plan_data or {}
            for agent_data in plan_data.get("agents", []):
                # Skill-reuse plans store agent IDs (strings); skip those here —
                # full AgentSpec dicts only.
                if not isinstance(agent_data, dict):
                    continue
                agents.append(
                    AgentResponse(
                        id=agent_data.get("id", ""),
                        name=agent_data.get("name", ""),
                        description=agent_data.get("description", ""),
                        goal=agent_data.get("goal", ""),
                        tools=agent_data.get("tools", []),
                        dependencies=agent_data.get("dependencies", []),
                        requires_human_approval=agent_data.get("requires_human_approval", False),
                        max_iterations=agent_data.get("max_iterations", 5),
                        max_tool_calls=agent_data.get("max_tool_calls", 20),
                        timeout_seconds=agent_data.get("timeout_seconds", 300),
                    )
                )
        return agents
    finally:
        await session.close()


@router.post("/execute")
async def execute_agent(request: ExecuteAgentRequest):
    """Execute a single agent directly (for testing/debugging).

    This runs one agent in isolation — no orchestration, no DAG.
    Useful for testing agent behavior before wiring up full workflows.
    """
    if request.agent_spec is None:
        raise HTTPException(status_code=422, detail="agent_spec is required")

    # Create runtime
    runtime = create_runtime(request.agent_spec)

    # Create context
    context = AgentContext(
        intent=request.intent,
        inputs=request.inputs,
        working_memory=request.working_memory,
    )

    # Execute
    result = await runtime.execute(context)

    return result.model_dump()