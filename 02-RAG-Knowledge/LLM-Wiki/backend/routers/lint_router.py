"""Lint router — wiki health check with SSE streaming."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import load_config, is_llm_configured
from backend.services import lint_service

router = APIRouter(prefix="/api/lint", tags=["lint"])


def _get_project_and_llm(project_id: str | None = None):
    cfg = load_config()
    pid = project_id or cfg.active_project_id
    if not pid:
        raise HTTPException(400, "No active project")
    project = next((p for p in cfg.projects if p.id == pid), None)
    if not project:
        raise HTTPException(404, "Project not found")
    return project, cfg.llm


class LintRequest(BaseModel):
    project_id: str | None = None


@router.post("/run")
async def run_lint(body: LintRequest):
    project, llm_cfg = _get_project_and_llm(body.project_id)

    if not is_llm_configured(llm_cfg):
        raise HTTPException(400, "LLM is not connected. Configure and test the LLM connection first.")

    async def event_stream():
        async for event in lint_service.run_lint(llm_cfg, project.root_path):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
