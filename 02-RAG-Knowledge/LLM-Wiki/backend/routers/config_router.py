"""Config router — LLM config CRUD and project management."""
from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import (
    AppConfig, LLMConfig, WikiProject,
    apply_env_fallback_to_llm, load_config, masked_config, save_config,
)
from backend.services import llm_service, local_model_service

router = APIRouter(prefix="/api/config", tags=["config"])


class LLMConfigUpdate(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    azure_endpoint: str = ""
    azure_deployment: str = ""
    azure_api_version: str = "2024-02-01"
    temperature: float = 0.3
    max_tokens: int = 4000


class ProjectCreate(BaseModel):
    name: str
    root_path: str


class ActiveProjectSet(BaseModel):
    project_id: str


@router.get("")
def get_config():
    cfg = load_config()
    return masked_config(cfg)


@router.post("/llm")
def update_llm_config(body: LLMConfigUpdate):
    cfg = load_config()
    # Preserve existing key if client sends masked placeholder
    if body.api_key == "***":
        body.api_key = cfg.llm.api_key
    # Any config change invalidates the connection status
    cfg.llm = LLMConfig(**body.model_dump(), llm_connected=False)
    save_config(cfg)
    return {"ok": True}


@router.post("/test-connection")
async def test_connection(body: LLMConfigUpdate | None = None):
    """Test connection using provided config, falling back to saved config.
    API key of '***' in body means use the saved key."""
    cfg = load_config()
    if body is not None:
        # Use provided config; restore saved key if masked, then fill empty
        # fields from environment / .env so Test Connection works without typing keys.
        data = body.model_dump()
        if data["api_key"] == "***":
            data["api_key"] = cfg.llm.api_key
        llm_cfg = apply_env_fallback_to_llm(LLMConfig(**data))
    else:
        llm_cfg = cfg.llm
    if not llm_cfg.provider:
        raise HTTPException(400, "No LLM provider configured")
    # Providers that require an API key — reject if missing
    keyless_providers = {"ollama", "lmstudio", "local-cpu"}
    if llm_cfg.provider not in keyless_providers and not llm_cfg.api_key:
        raise HTTPException(400, "API key is required. Please enter your API key.")
    try:
        result = await llm_service.test_connection(llm_cfg)
        # Persist the successful connection status
        cfg.llm = llm_cfg.model_copy(update={"llm_connected": True})
        save_config(cfg)
        return {"ok": True, "response": result}
    except Exception as e:
        # Mark as not connected on failure
        cfg.llm = llm_cfg.model_copy(update={"llm_connected": False})
        save_config(cfg)
        raise HTTPException(400, str(e))


@router.get("/projects")
def list_projects():
    cfg = load_config()
    return cfg.projects


@router.post("/projects")
def create_project(body: ProjectCreate):
    cfg = load_config()
    project = WikiProject(
        id=str(uuid.uuid4()),
        name=body.name,
        root_path=body.root_path,
    )
    cfg.projects.append(project)
    if not cfg.active_project_id:
        cfg.active_project_id = project.id
    save_config(cfg)
    return project


@router.delete("/projects/{project_id}")
def delete_project(project_id: str):
    cfg = load_config()
    cfg.projects = [p for p in cfg.projects if p.id != project_id]
    if cfg.active_project_id == project_id:
        cfg.active_project_id = cfg.projects[0].id if cfg.projects else None
    save_config(cfg)
    return {"ok": True}


@router.post("/projects/active")
def set_active_project(body: ActiveProjectSet):
    cfg = load_config()
    if not any(p.id == body.project_id for p in cfg.projects):
        raise HTTPException(404, "Project not found")
    cfg.active_project_id = body.project_id
    save_config(cfg)
    return {"ok": True}


@router.delete("/projects/active")
def clear_active_project():
    cfg = load_config()
    cfg.active_project_id = None
    save_config(cfg)
    return {"ok": True}


# ── Local CPU model endpoints ────────────────────────────────────────────────

@router.get("/local-model/models")
def local_model_list():
    """List only downloaded local CPU models that are ready to use."""
    return [
        {
            "id": m["id"],
            "label": m["label"],
            "size": m["size"],
            "repo": m["repo"],
            "filename": m["filename"],
            "downloaded": True,
        }
        for m in local_model_service.AVAILABLE_MODELS
        if local_model_service.is_model_downloaded(m["id"])
    ]


@router.get("/local-model/status")
def local_model_status():
    """Check if the currently selected local model is downloaded and ready."""
    cfg = load_config()
    model_id = cfg.llm.model if cfg.llm.provider == "local-cpu" else None
    return {
        "downloaded": local_model_service.is_model_downloaded(model_id),
        "model_id": model_id or local_model_service.DEFAULT_MODEL_ID,
        "model_path": str(local_model_service.get_model_path(model_id)),
        "downloaded_models": local_model_service.get_downloaded_models(),
    }


class LocalModelDownloadRequest(BaseModel):
    model_id: str


@router.post("/local-model/download")
def local_model_download(body: LocalModelDownloadRequest):
    """Download a specific GGUF model. Blocking — may take several minutes."""
    if local_model_service.is_model_downloaded(body.model_id):
        return {"ok": True, "message": "Model already downloaded"}
    try:
        path = local_model_service.download_model(body.model_id)
        return {"ok": True, "message": "Model downloaded successfully", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Download failed: {e}")
