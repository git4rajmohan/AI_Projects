"""API routes for plans.

POST /api/plans — Generate a plan for a task
GET  /api/plans/{id} — Get plan details
POST /api/plans/{id}/approve — Approve a plan
POST /api/plans/{id}/reject — Reject a plan
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.agent import AgentSpec
from app.models.plan import PlanModel
from app.models.plan_schema import PlanSpec
from app.models.task import TaskModel
from app.planner.planner import get_planner
from app.planner.plan_validator import PlanValidationError
from app.skills.discovery import discover_skills

router = APIRouter()
logger = logging.getLogger(__name__)


class GeneratePlanRequest(BaseModel):
    """Request to generate a plan for a task."""

    task_id: str


class PlanResponse(BaseModel):
    """Plan response."""

    id: str
    task_id: str
    objective: str
    summary: str = ""
    status: str
    estimated_cost: float = 0.0
    estimated_duration_seconds: int = 60
    requires_approval: bool = True
    plan_data: dict = {}
    matched_skills: list[dict] = []


@router.post("", response_model=PlanResponse)
async def generate_plan(request: GeneratePlanRequest, db: AsyncSession = Depends(get_db)):
    """Generate a structured plan for a task.

    Flow:
    1. Fetch the task and its intent
    2. Search for matching skills (skill discovery)
    3. If a strong match is found, reuse that skill's plan
    4. Otherwise, generate a new plan via the LLM Planner
    5. Save the plan to the database
    """
    # 1. Fetch task
    result = await db.execute(select(TaskModel).where(TaskModel.id == request.task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Update task status
    task.status = "planning"
    await db.flush()

    # 2. Skill discovery
    matched_skills = await discover_skills(task.intent, db)

    # 3. Check for strong skill match (score > 0.5)
    if matched_skills and matched_skills[0].score > 0.5:
        # Reuse existing skill's plan
        best_match = matched_skills[0]
        logger.info(f"Reusing skill '{best_match.skill.name}' (score={best_match.score:.2f})")

        spec_data = best_match.version.spec_data

        # Reconstruct full AgentSpecs from the skill's agent definitions.
        # SkillSpec.agents stores string IDs; execution needs full AgentSpec objects.
        from app.skills.yaml_parser import parse_agent_specs_from_yaml

        agent_specs = parse_agent_specs_from_yaml(spec_data)
        if not agent_specs:
            # Fallback: build minimal specs from the tool list
            skill_tools = spec_data.get("tools", [])
            agent_specs = [
                AgentSpec(
                    id=aid,
                    name=aid,
                    description=spec_data.get("description", ""),
                    goal=spec_data.get("description", ""),
                    tools=skill_tools if i == 0 else [],
                )
                for i, aid in enumerate(spec_data.get("agents", []))
            ]

        from app.models.plan_schema import EvaluationSpec, MemorySpec, WorkflowSpec

        reuse_plan_data = {
            "task_id": task.id,
            "objective": spec_data.get("objective", task.intent),
            "summary": spec_data.get("summary", f"Reusing skill: {best_match.skill.name}"),
            "agents": [a.model_dump() for a in agent_specs],
            "workflow": spec_data.get("workflow", {"type": "dag", "nodes": [], "edges": []}),
            "evaluation": spec_data.get("evaluation", {"criteria": ["completeness"], "threshold": 0.7}),
            "permissions": spec_data.get("permissions", {}),
            "estimated_cost": spec_data.get("estimated_cost", 0.0),
            "estimated_duration_seconds": spec_data.get("estimated_duration_seconds", 60),
            "requires_approval": spec_data.get("requires_approval", True),
            "matched_skills": [str(best_match.skill.id)],
        }
        # Validate into a proper PlanSpec shape before persisting
        try:
            validated = PlanSpec(**reuse_plan_data)
            reuse_plan_data = validated.model_dump()
        except Exception as e:
            logger.warning(f"Skill-reuse plan validation failed: {e}; falling back to LLM planner")
            reuse_plan_data = None

        if reuse_plan_data is not None:
            plan = PlanModel(
                id=str(uuid.uuid4()),
                task_id=task.id,
                objective=reuse_plan_data["objective"],
                summary=reuse_plan_data["summary"],
                plan_data=reuse_plan_data,
                status="created",
                estimated_cost=reuse_plan_data["estimated_cost"],
                estimated_duration_seconds=reuse_plan_data["estimated_duration_seconds"],
                requires_approval=reuse_plan_data["requires_approval"],
            )
        else:
            plan = None
    else:
        plan = None

    if plan is None:
        # 4. Generate new plan via LLM Planner
        logger.info(f"Generating new plan for task {task.id}")
        try:
            planner = get_planner()
            plan_spec = await planner.create_plan(task_id=task.id, intent_text=task.intent)

            # Convert PlanSpec to dict for storage
            plan_data = plan_spec.model_dump()

            plan = PlanModel(
                id=str(uuid.uuid4()),
                task_id=task.id,
                objective=plan_spec.objective,
                summary=plan_spec.summary,
                plan_data=plan_data,
                status="created",
                estimated_cost=plan_spec.estimated_cost,
                estimated_duration_seconds=plan_spec.estimated_duration_seconds,
                requires_approval=plan_spec.requires_approval,
            )
        except PlanValidationError as e:
            task.status = "failed"
            raise HTTPException(status_code=422, detail=f"Plan validation failed: {e.errors}")
        except Exception as e:
            task.status = "failed"
            logger.error(f"Plan generation failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Plan generation failed: {str(e)}")

    # 5. Save plan
    db.add(plan)
    task.status = "planned"
    await db.flush()

    return PlanResponse(
        id=plan.id,
        task_id=plan.task_id,
        objective=plan.objective,
        summary=plan.summary,
        status=plan.status,
        estimated_cost=plan.estimated_cost,
        estimated_duration_seconds=plan.estimated_duration_seconds,
        requires_approval=plan.requires_approval,
        plan_data=plan.plan_data,
        matched_skills=[m.to_dict() for m in matched_skills],
    )


@router.get("", response_model=list[PlanResponse])
async def list_plans(task_id: str | None = None, db: AsyncSession = Depends(get_db)):
    """List plans, optionally filtered by task_id."""
    query = select(PlanModel).order_by(PlanModel.created_at.desc())
    if task_id:
        query = query.where(PlanModel.task_id == task_id)
    result = await db.execute(query)
    plans = result.scalars().all()
    return [
        PlanResponse(
            id=p.id,
            task_id=p.task_id,
            objective=p.objective,
            summary=p.summary,
            status=p.status,
            estimated_cost=p.estimated_cost,
            estimated_duration_seconds=p.estimated_duration_seconds,
            requires_approval=p.requires_approval,
            plan_data=p.plan_data,
        )
        for p in plans
    ]


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    """Get plan details by ID."""
    result = await db.execute(select(PlanModel).where(PlanModel.id == plan_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanResponse(
        id=plan.id,
        task_id=plan.task_id,
        objective=plan.objective,
        summary=plan.summary,
        status=plan.status,
        estimated_cost=plan.estimated_cost,
        estimated_duration_seconds=plan.estimated_duration_seconds,
        requires_approval=plan.requires_approval,
        plan_data=plan.plan_data,
    )


@router.post("/{plan_id}/approve")
async def approve_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    """Approve a plan for execution."""
    result = await db.execute(select(PlanModel).where(PlanModel.id == plan_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.status not in ("created", "rejected", "completed", "failed"):
        raise HTTPException(status_code=400, detail=f"Plan in status '{plan.status}' cannot be approved")

    plan.status = "approved"

    # Update task status
    task_result = await db.execute(select(TaskModel).where(TaskModel.id == plan.task_id))
    task = task_result.scalar_one_or_none()
    if task:
        task.status = "approved"

    await db.flush()

    return {"status": "approved", "plan_id": plan_id}


@router.post("/{plan_id}/reject")
async def reject_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    """Reject a plan."""
    result = await db.execute(select(PlanModel).where(PlanModel.id == plan_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan.status = "rejected"

    # Update task status
    task_result = await db.execute(select(TaskModel).where(TaskModel.id == plan.task_id))
    task = task_result.scalar_one_or_none()
    if task:
        task.status = "rejected"

    await db.flush()

    return {"status": "rejected", "plan_id": plan_id}