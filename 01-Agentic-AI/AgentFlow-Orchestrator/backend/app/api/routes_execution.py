"""API routes for execution.

POST /api/executions — Start execution of an approved plan
GET  /api/executions/{id} — Get execution status
GET  /api/executions/{id}/events — Get execution events (SSE stream)
POST /api/executions/{id}/cancel — Cancel a running execution
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db import database
from app.models.execution import ExecutionModel
from app.models.plan import PlanModel
from app.models.plan_schema import PlanSpec
from app.models.task import TaskModel
from app.orchestrator.engine import OrchestrationError, get_orchestrator
from app.orchestrator.events import get_event_manager
from app.orchestrator.state import get_state_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class StartExecutionRequest(BaseModel):
    """Request to start executing a plan."""

    plan_id: str
    evaluate: bool = True


class ExecutionResponse(BaseModel):
    """Execution response."""

    id: str
    task_id: str
    plan_id: str
    status: str
    state: dict = {}
    total_tool_calls: int = 0
    total_cost: float = 0.0
    result: dict | None = None
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@router.post("", response_model=ExecutionResponse)
async def start_execution(request: StartExecutionRequest, db: AsyncSession = Depends(get_db)):
    """Start executing an approved plan.

    1. Fetch the plan and verify it's approved
    2. Reconstruct the PlanSpec from stored plan_data
    3. Create an execution record
    4. Launch the orchestrator in the background
    5. Return the execution ID immediately
    """
    # Fetch plan
    result = await db.execute(select(PlanModel).where(PlanModel.id == request.plan_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Plan status is '{plan.status}' — must be 'approved' before execution",
        )

    # Reconstruct PlanSpec from stored data
    try:
        plan_spec = PlanSpec(**plan.plan_data)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reconstruct plan from stored data: {e}",
        )

    # Use the original task intent (preserves attached file paths) rather than
    # the LLM-paraphrased plan.objective, which often drops literal file paths.
    task_result = await db.execute(select(TaskModel).where(TaskModel.id == plan.task_id))
    task = task_result.scalar_one_or_none()
    execution_intent = task.intent if task else plan.objective

    # Create execution record
    state_manager = get_state_manager()
    state = await state_manager.create_execution(
        task_id=plan.task_id,
        plan_id=plan.id,
    )

    # Update plan status
    plan.status = "executing"
    await db.flush()

    # Launch orchestrator in the background
    orchestrator = get_orchestrator()

    async def _run_orchestration():
        final_status = "failed"
        try:
            if request.evaluate:
                # Evaluate the result and replan on failure (instruction.md §23-24)
                final_state, _ = await orchestrator.execute_with_evaluation(
                    plan=plan_spec,
                    task_id=plan.task_id,
                    execution_id=state.execution_id,
                    intent=execution_intent,
                )
            else:
                final_state = await orchestrator.execute(
                    plan=plan_spec,
                    task_id=plan.task_id,
                    execution_id=state.execution_id,
                    intent=execution_intent,
                )
            final_status = "completed" if final_state.status == "completed" else "failed"
        except Exception as e:
            logger.error(f"Background orchestration failed: {e}", exc_info=True)
        finally:
            # Plan status must leave 'executing' or it can never be re-approved/re-run.
            async with database.async_session_factory() as bg_db:
                bg_result = await bg_db.execute(select(PlanModel).where(PlanModel.id == request.plan_id))
                bg_plan = bg_result.scalar_one_or_none()
                if bg_plan is not None:
                    bg_plan.status = final_status
                    await bg_db.commit()

    # Fire and forget — the orchestrator persists state to DB
    asyncio.create_task(_run_orchestration())

    # Return execution details immediately
    return ExecutionResponse(
        id=state.execution_id,
        task_id=state.task_id,
        plan_id=state.plan_id,
        status=state.status,
        state=state.to_dict(),
        total_tool_calls=state.total_tool_calls,
        total_cost=state.total_cost,
        created_at=None,  # Will be set by DB
    )


@router.get("", response_model=list[ExecutionResponse])
async def list_executions(task_id: str | None = None, db: AsyncSession = Depends(get_db)):
    """List executions, optionally filtered by task_id."""
    query = select(ExecutionModel).order_by(ExecutionModel.created_at.desc())
    if task_id:
        query = query.where(ExecutionModel.task_id == task_id)
    result = await db.execute(query)
    executions = result.scalars().all()
    return [
        ExecutionResponse(
            id=e.id,
            task_id=e.task_id,
            plan_id=e.plan_id,
            status=e.status,
            state=e.state or {},
            total_tool_calls=e.total_tool_calls or 0,
            total_cost=e.total_cost or 0.0,
            result=e.result,
            error=e.error,
            created_at=e.created_at.isoformat() if e.created_at else None,
            started_at=e.started_at.isoformat() if e.started_at else None,
            completed_at=e.completed_at.isoformat() if e.completed_at else None,
        )
        for e in executions
    ]


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(execution_id: str, db: AsyncSession = Depends(get_db)):
    """Get execution status and details."""
    result = await db.execute(
        select(ExecutionModel).where(ExecutionModel.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    return ExecutionResponse(
        id=execution.id,
        task_id=execution.task_id,
        plan_id=execution.plan_id,
        status=execution.status,
        state=execution.state or {},
        total_tool_calls=execution.total_tool_calls or 0,
        total_cost=execution.total_cost or 0.0,
        result=execution.result,
        error=execution.error,
        created_at=execution.created_at.isoformat() if execution.created_at else None,
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        completed_at=execution.completed_at.isoformat() if execution.completed_at else None,
    )


@router.get("/{execution_id}/events")
async def get_execution_events(execution_id: str, db: AsyncSession = Depends(get_db)):
    """Get execution events.

    Returns all events for this execution as a JSON array.
    (SSE streaming can be added later — for now, return a snapshot.)
    """
    # Verify execution exists
    result = await db.execute(
        select(ExecutionModel).where(ExecutionModel.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    # Get events from the event manager
    event_manager = get_event_manager()
    events = await event_manager.get_events(execution_id)
    return {"execution_id": execution_id, "events": events, "count": len(events)}


@router.post("/{execution_id}/cancel")
async def cancel_execution(execution_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a running execution."""
    result = await db.execute(
        select(ExecutionModel).where(ExecutionModel.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status not in ("running", "pending", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Execution status is '{execution.status}' — can only cancel running/pending/paused executions",
        )

    orchestrator = get_orchestrator()
    cancelled = orchestrator.cancel(execution_id)

    return {
        "execution_id": execution_id,
        "cancel_requested": cancelled,
        "message": "Cancellation requested. Execution will stop at the next checkpoint." if cancelled else "Execution not actively running.",
    }


@router.get("/{execution_id}/evaluation")
async def get_execution_evaluation(execution_id: str, db: AsyncSession = Depends(get_db)):
    """Get the evaluation result for a completed execution.

    If the execution was run with evaluation, the result is stored
    in the execution's result dict under the 'evaluation' key.
    """
    result = await db.execute(
        select(ExecutionModel).where(ExecutionModel.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.result is None:
        raise HTTPException(status_code=404, detail="No evaluation result available for this execution")

    evaluation = execution.result.get("evaluation")
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Execution was not evaluated")

    return {
        "execution_id": execution_id,
        "evaluation": evaluation,
    }