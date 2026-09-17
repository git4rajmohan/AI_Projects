"""API routes for tasks.

POST /api/tasks — Create a task from user intent
GET  /api/tasks — List recent tasks
GET  /api/tasks/{id} — Get task details
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.task import TaskModel

router = APIRouter()


class CreateTaskRequest(BaseModel):
    """Request to create a new task from user intent."""

    intent: str = Field(..., min_length=1, description="Natural-language description of what the user wants")
    user_id: str | None = Field(None, description="Optional user ID")


class TaskResponse(BaseModel):
    """Task response."""

    id: str
    intent: str
    status: str
    user_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.post("", response_model=TaskResponse)
async def create_task(request: CreateTaskRequest, db: AsyncSession = Depends(get_db)):
    """Create a new task from a user's natural-language intent."""
    task = TaskModel(
        id=str(uuid.uuid4()),
        intent=request.intent,
        status="created",
        user_id=request.user_id,
    )
    db.add(task)
    await db.flush()
    return TaskResponse(**task.to_dict())


@router.get("", response_model=list[TaskResponse])
async def list_tasks(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """List recent tasks, most recent first."""
    result = await db.execute(
        select(TaskModel).order_by(TaskModel.created_at.desc()).limit(limit)
    )
    tasks = result.scalars().all()
    return [TaskResponse(**t.to_dict()) for t in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Get task details by ID."""
    result = await db.execute(select(TaskModel).where(TaskModel.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**task.to_dict())