"""API routes for model routing.

POST /api/models/route — Get model routing info for a task
GET  /api/models/tiers — List available model tiers
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.llm.router import MODEL_NAMES, MODEL_TIER_DEFAULT, MODEL_TIER_FAST, MODEL_TIER_REASONING, get_model_router

router = APIRouter()
logger = logging.getLogger(__name__)


class RouteRequest(BaseModel):
    """Request to get model routing info."""

    intent: str = ""
    agent_model: str = ""
    agent_tools: list[str] = []
    plan_agent_count: int = 0


@router.get("/tiers")
async def list_tiers():
    """List available model tiers and their model names."""
    return {
        "tiers": [
            {"name": MODEL_TIER_FAST, "model": MODEL_NAMES[MODEL_TIER_FAST], "description": "Fast/cheap model for simple tasks"},
            {"name": MODEL_TIER_DEFAULT, "model": MODEL_NAMES[MODEL_TIER_DEFAULT], "description": "Default model for general tasks"},
            {"name": MODEL_TIER_REASONING, "model": MODEL_NAMES[MODEL_TIER_REASONING], "description": "High-reasoning model for complex tasks"},
        ]
    }


@router.post("/route")
async def route_model(request: RouteRequest):
    """Get model routing information for a task.

    Returns the recommended tier, model name, and routing reasons.
    Does NOT create a model instance — just returns routing info.
    """
    from app.models.agent import AgentSpec
    from app.models.plan_schema import PlanSpec

    agent_spec = None
    if request.agent_model or request.agent_tools:
        agent_spec = AgentSpec(
            id="route_check",
            name="Route Check",
            goal="",
            model=request.agent_model,
            tools=request.agent_tools,
        )

    plan = None
    if request.plan_agent_count > 0:
        # Create a minimal plan for routing analysis
        plan = PlanSpec(
            task_id="route_check",
            objective="Route check",
            agents=[agent_spec] if agent_spec else [],
        )

    router = get_model_router()
    info = router.get_routing_info(
        intent_text=request.intent,
        agent_spec=agent_spec,
        plan=plan,
    )

    return info