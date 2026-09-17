"""Policy module — permission checks and human approval management.

Phase 7: Human Approval
"""

from app.policy.approval import (
    ApprovalAlreadyResolvedError,
    ApprovalManager,
    ApprovalNotFoundError,
    get_approval_manager,
)
from app.policy.engine import (
    APPROVAL_REQUIRED_LEVELS,
    PERMISSION_LEVELS,
    PolicyDecision,
    PolicyEngine,
    get_policy_engine,
)

__all__ = [
    "ApprovalAlreadyResolvedError",
    "ApprovalManager",
    "ApprovalNotFoundError",
    "get_approval_manager",
    "APPROVAL_REQUIRED_LEVELS",
    "PERMISSION_LEVELS",
    "PolicyDecision",
    "PolicyEngine",
    "get_policy_engine",
]