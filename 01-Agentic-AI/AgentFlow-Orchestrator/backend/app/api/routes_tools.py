"""API routes for tools.

GET /api/tools — List registered tools
GET /api/tools/{id} — Get tool details
POST /api/tools/{id}/execute — Execute a tool directly (for testing)
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.tool_schema import ToolSpec
from app.tools.registry import ToolNotFoundError, get_registry

router = APIRouter()
logger = logging.getLogger(__name__)


class ToolResponse(BaseModel):
    """Tool response."""

    id: str
    name: str
    description: str
    permission_level: str
    input_schema: dict = {}
    output_schema: dict = {}
    enabled: bool = True


class ExecuteToolRequest(BaseModel):
    """Request to execute a tool directly (for testing/debugging)."""

    params: dict = {}


@router.get("", response_model=list[ToolResponse])
async def list_tools():
    """List all registered tools."""
    registry = get_registry()
    tools = registry.list()
    return [
        ToolResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            permission_level=t.permission_level,
            input_schema=t.input_schema,
            output_schema=t.output_schema,
            enabled=t.enabled,
        )
        for t in tools
    ]


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(tool_id: str):
    """Get tool details by ID."""
    registry = get_registry()
    try:
        tool = registry.get(tool_id)
    except ToolNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found")
    spec = tool.spec
    return ToolResponse(
        id=spec.id,
        name=spec.name,
        description=spec.description,
        permission_level=spec.permission_level,
        input_schema=spec.input_schema,
        output_schema=spec.output_schema,
        enabled=spec.enabled,
    )


@router.post("/{tool_id}/execute")
async def execute_tool(tool_id: str, request: ExecuteToolRequest):
    """Execute a tool directly with given parameters.

    This is primarily for testing/debugging. In normal operation,
    tools are executed by agents during workflow execution.
    """
    registry = get_registry()
    try:
        tool = registry.get(tool_id)
    except ToolNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found")

    if not tool.spec.enabled:
        raise HTTPException(status_code=400, detail=f"Tool '{tool_id}' is disabled")

    result = await tool.execute(**request.params)
    return result