"""API routes for skills.

GET  /api/skills — List all skills
POST /api/skills — Create a skill
GET  /api/skills/recommend — Get skill recommendations for an intent
GET  /api/skills/{id} — Get skill details
PUT  /api/skills/{id} — Update a skill
DELETE /api/skills/{id} — Delete a skill
POST /api/skills/{id}/run — Run a skill
GET  /api/skills/{id}/export — Export a skill (as JSON)
POST /api/skills/{id}/export — Export a skill as .skill.zip
POST /api/skills/upload — Upload and import a .skill.zip
POST /api/skills/preview — Preview a .skill.zip without installing
"""

import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from io import BytesIO

from app.models.skill_schema import SkillSpec
from app.skills.creation import SkillCreationError
from app.skills.execution import SkillExecutionError, run_skill
from app.skills.import_export import (
    SkillExportError,
    SkillImportError,
    export_skill_to_zip,
    import_skill_from_zip,
)
from app.skills.recommender import get_skill_recommender
from app.skills.registry import SkillNotFoundError, get_skill_registry

router = APIRouter()
logger = logging.getLogger(__name__)


class CreateSkillRequest(BaseModel):
    """Request to create a new skill."""

    spec: SkillSpec
    author: str | None = None


class UpdateSkillRequest(BaseModel):
    """Request to update skill metadata."""

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None


class CreateVersionRequest(BaseModel):
    """Request to create a new version of a skill."""

    spec: SkillSpec


class RunSkillRequest(BaseModel):
    """Request to run a skill."""

    task_id: str = Field(..., description="Task ID to associate with this execution")
    intent: str = Field("", description="Optional override intent")


class SkillResponse(BaseModel):
    """Skill response."""

    id: str
    name: str
    description: str
    author: str | None = None
    tags: list[str] = []
    enabled: bool = True
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_duration_seconds: float = 0.0
    avg_cost: float = 0.0
    evaluation_score: float = 0.0
    active_version: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.get("", response_model=list[SkillResponse])
async def list_skills(include_disabled: bool = False):
    """List all registered skills."""
    registry = get_skill_registry()
    skills = await registry.list_skills(include_disabled=include_disabled)
    return skills


@router.get("/recommend")
async def recommend_skills(
    intent: str = Query(..., description="User intent to find matching skills"),
    max_results: int = Query(5, ge=1, le=20),
):
    """Get skill recommendations for a user intent.

    Uses keyword matching, usage history, success rates, and recency
    to rank skills by relevance.
    """
    recommender = get_skill_recommender()
    recommendations = await recommender.recommend(
        intent_text=intent,
        max_results=max_results,
    )
    return {"recommendations": [r.to_dict() for r in recommendations], "count": len(recommendations)}


@router.post("", response_model=dict)
async def create_skill(request: CreateSkillRequest):
    """Create a new skill with an initial version (1.0.0)."""
    registry = get_skill_registry()
    try:
        result = await registry.create_skill(request.spec, author=request.author)
    except Exception as e:
        logger.error(f"Skill creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    return result


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str):
    """Get skill details by ID."""
    registry = get_skill_registry()
    skill = await registry.get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: str, request: UpdateSkillRequest):
    """Update skill metadata (name, description, tags, enabled)."""
    registry = get_skill_registry()
    result = await registry.update_skill(
        skill_id,
        name=request.name,
        description=request.description,
        tags=request.tags,
        enabled=request.enabled,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return result


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete a skill and all its versions."""
    registry = get_skill_registry()
    deleted = await registry.delete_skill(skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "deleted", "skill_id": skill_id}


@router.post("/{skill_id}/versions")
async def create_version(skill_id: str, request: CreateVersionRequest):
    """Create a new version of an existing skill."""
    registry = get_skill_registry()
    try:
        result = await registry.create_version(skill_id, request.spec)
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail="Skill not found")
    return result


@router.post("/{skill_id}/activate/{version}")
async def activate_version(skill_id: str, version: str):
    """Activate a specific version of a skill."""
    registry = get_skill_registry()
    activated = await registry.activate_version(skill_id, version)
    if not activated:
        raise HTTPException(status_code=404, detail=f"Version '{version}' not found for skill '{skill_id}'")
    return {"status": "activated", "skill_id": skill_id, "version": version}


@router.post("/{skill_id}/run")
async def run_skill_endpoint(skill_id: str, request: RunSkillRequest):
    """Run a skill — creates an execution and launches the orchestrator."""
    try:
        result = await run_skill(
            skill_id=skill_id,
            task_id=request.task_id,
            intent=request.intent,
        )
    except SkillExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/{skill_id}/export")
async def export_skill(skill_id: str):
    """Export a skill as JSON (for sharing or backup).

    Phase 8 will add .skill.zip packaging with YAML manifest.
    """
    registry = get_skill_registry()
    skill = await registry.get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    active_version = skill.get("active_version")
    if active_version is None:
        raise HTTPException(status_code=400, detail="Skill has no active version to export")

    return {
        "skill": skill,
        "format": "json",
        "version": "1.0",
    }


@router.post("/{skill_id}/export")
async def export_skill_zip(skill_id: str):
    """Export a skill as a .skill.zip download."""
    try:
        zip_bytes, filename = await export_skill_to_zip(skill_id)
    except SkillExportError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StreamingResponse(
        BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/upload")
async def upload_skill(file: UploadFile = File(...), install: bool = True):
    """Upload and import a .skill.zip file.

    Import pipeline:
    1. Extract the zip
    2. Parse skill.yaml
    3. Validate (required fields, tools, agents)
    4. Security scan
    5. Install (if install=True and validation passes)

    Never executes the uploaded skill.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    content = await file.read()
    try:
        result = await import_skill_from_zip(content, install=install)
    except SkillImportError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/preview")
async def preview_skill(file: UploadFile = File(...)):
    """Preview a .skill.zip without installing it.

    Validates the skill and returns the parsed spec + any issues.
    Does not install or execute the skill.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    content = await file.read()
    try:
        result = await import_skill_from_zip(content, install=False)
    except SkillImportError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result