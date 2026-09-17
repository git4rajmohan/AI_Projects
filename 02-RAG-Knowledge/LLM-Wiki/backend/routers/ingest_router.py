"""Ingest router — scaffold, file listing, upload, run/rebuild with SSE streaming."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import load_config, is_llm_configured
from backend.services import wiki_manager, ingest_service

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


def _get_project(project_id: str | None = None):
    cfg = load_config()
    pid = project_id or cfg.active_project_id
    if not pid:
        raise HTTPException(400, "No active project")
    project = next((p for p in cfg.projects if p.id == pid), None)
    if not project:
        raise HTTPException(404, "Project not found")
    return project, cfg.llm


class ScaffoldRequest(BaseModel):
    project_id: str | None = None


class IngestRequest(BaseModel):
    file_paths: List[str] | None = None
    rebuild: bool = False
    project_id: str | None = None


class RemoveFileRequest(BaseModel):
    project_id: str | None = None
    file_path: str  # relative to wiki root, e.g. "Clippings/Business_Requirements.docx"


@router.post("/scaffold")
def scaffold(body: ScaffoldRequest):
    project, _ = _get_project(body.project_id)
    wiki_manager.scaffold_wiki(project.root_path)
    return {"ok": True, "root_path": project.root_path}


@router.get("/files")
def list_files(project_id: str | None = None):
    project, _ = _get_project(project_id)
    return {"files": wiki_manager.list_source_files(project.root_path)}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), project_id: str | None = Form(None)):
    project, _ = _get_project(project_id)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(413, "File too large (max 10 MB)")
    saved_path = wiki_manager.save_file_to_clippings(
        project.root_path, file.filename or "upload.md", content
    )
    return {"ok": True, "path": saved_path}


@router.delete("/file")
def remove_file(body: RemoveFileRequest):
    """Delete a source file from Clippings, its wiki/sources page, and rebuild index."""
    project, _ = _get_project(body.project_id)
    root = wiki_manager._effective_root(project.root_path)

    source_file = (root / body.file_path).resolve()
    # Security: must stay within project root
    try:
        source_file.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid path")
    if not source_file.exists():
        raise HTTPException(404, "File not found")

    source_file.unlink()

    # Try to delete the corresponding wiki/sources/<slug>.md
    # Slug: filename lowercased, underscores/spaces → hyphens, keep original extension, append .md
    filename = source_file.name
    slug = filename.lower().replace("_", "-").replace(" ", "-")
    source_page = root / "wiki" / "sources" / f"{slug}.md"
    source_page_deleted = False
    if source_page.exists():
        source_page.unlink()
        source_page_deleted = True

    # Rebuild index to remove the deleted source's row
    try:
        wiki_manager.auto_rebuild_index(project.root_path)
    except Exception:
        pass

    return {"ok": True, "source_page_deleted": source_page_deleted}


@router.post("/run")
async def run_ingest(body: IngestRequest):
    project, llm_cfg = _get_project(body.project_id)

    if not is_llm_configured(llm_cfg):
        raise HTTPException(400, "LLM is not connected. Configure and test the LLM connection first.")

    # Resolve file list: explicit selection or all source files
    file_paths = body.file_paths
    if not file_paths:
        file_paths = [f["path"] for f in wiki_manager.list_source_files(project.root_path)]

    if not file_paths:
        raise HTTPException(400, "No source files found to ingest")

    async def event_stream():
        async for event in ingest_service.ingest_files(
            llm_cfg, project.root_path, file_paths, rebuild=body.rebuild
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
