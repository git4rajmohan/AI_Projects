"""API routes for approvals.

GET  /api/approvals — List pending approvals
GET  /api/approvals/{id} — Get approval details
POST /api/approvals/{id}/approve — Approve a request
POST /api/approvals/{id}/reject — Reject a request
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.policy.approval import (
    ApprovalAlreadyResolvedError,
    ApprovalNotFoundError,
    get_approval_manager,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class ResolveApprovalRequest(BaseModel):
    """Request to approve or reject an approval."""

    user_id: str | None = None


@router.get("")
async def list_approvals(execution_id: str | None = None):
    """List pending approval requests.

    Args:
        execution_id: Optional filter by execution ID.
    """
    manager = get_approval_manager()
    approvals = await manager.list_pending(execution_id=execution_id)
    return {"approvals": approvals, "count": len(approvals)}


@router.get("/{approval_id}")
async def get_approval(approval_id: str):
    """Get approval details by ID."""
    manager = get_approval_manager()
    approval = await manager.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/{approval_id}/approve")
async def approve_request(approval_id: str, request: ResolveApprovalRequest):
    """Approve a pending approval request."""
    manager = get_approval_manager()
    try:
        result = await manager.approve(approval_id, user_id=request.user_id)
    except ApprovalNotFoundError:
        raise HTTPException(status_code=404, detail="Approval not found")
    except ApprovalAlreadyResolvedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/{approval_id}/reject")
async def reject_request(approval_id: str, request: ResolveApprovalRequest):
    """Reject a pending approval request."""
    manager = get_approval_manager()
    try:
        result = await manager.reject(approval_id, user_id=request.user_id)
    except ApprovalNotFoundError:
        raise HTTPException(status_code=404, detail="Approval not found")
    except ApprovalAlreadyResolvedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result