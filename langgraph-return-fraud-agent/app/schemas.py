"""Pydantic state schemas and API payload contracts for the return agent."""
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class ItemCondition(str, Enum):
    """Condition classification of the returned item."""

    damaged_defective = "damaged_defective"
    buyer_remorse = "buyer_remorse"
    unknown = "unknown"


class ReturnStatus(str, Enum):
    """Lifecycle status of a return request."""

    pending = "pending"
    awaiting_photo = "awaiting_photo"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"
    denied_policy = "denied_policy"


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------
class ReturnState(BaseModel):
    """The state carried through the LangGraph state machine.

    Used as the `StateGraph` state schema; plain dict-compatible so LangGraph
    can treat it as a TypedDict-style mapping while we keep Pydantic validation.
    """

    # -- identifiers -------------------------------------------------------
    order_id: str
    customer_id: str = ""
    item_id: str

    # -- request payload ---------------------------------------------------
    reason_text: str
    photo_provided: bool = False
    photo_url: Optional[str] = None
    photo_retry_count: int = 0

    # -- derived classification ---------------------------------------------
    item_condition: ItemCondition = ItemCondition.unknown

    # -- order facts (filled by validate_policy_node) -------------------------
    order_date: Optional[str] = None
    item_value: float = 0.0

    # -- computed values ----------------------------------------------------
    shipping_fee: float = 0.0
    refund_amount: float = 0.0
    fraud_score: float = 0.0
    fraud_flags: List[str] = Field(default_factory=list)

    # -- workflow control ----------------------------------------------------
    status: ReturnStatus = ReturnStatus.pending
    manager_note: Optional[str] = None
    decision_log: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request/response contracts
# ---------------------------------------------------------------------------
class ReturnRequest(BaseModel):
    """POST /returns payload."""

    order_id: str
    item_id: str
    reason_text: str
    photo_provided: bool = False
    photo_url: Optional[str] = None


class ReturnResponse(BaseModel):
    """Response for most return-related endpoints."""

    thread_id: str
    status: ReturnStatus
    message: str
    next_action: Optional[Literal["submit_photo", "await_manager", "none"]] = None
    # Identifiers from the workflow state — always populated so list views
    # (e.g. the manager approval queue) can identify a return without a
    # second per-thread lookup.
    order_id: Optional[str] = None
    item_id: Optional[str] = None
    #: LLM classification of the return reason ('damaged_defective' |
    #: 'buyer_remorse'); 'unknown' until the classify node has run.
    item_condition: Optional[str] = None
    reason_text: Optional[str] = None
    refund_amount: Optional[float] = None
    shipping_fee: Optional[float] = None
    fraud_score: Optional[float] = None
    fraud_flags: List[str] = Field(default_factory=list)
    manager_note: Optional[str] = None
    #: Audit trail appended by every graph node — lets UIs render a
    #: completed-vs-pending workflow pipeline without re-deriving stages.
    decision_log: List[str] = Field(default_factory=list)


class OrderSummary(BaseModel):
    """GET /orders payload — one mock order the UI can offer for a new return."""

    order_id: str
    item_id: str
    item_name: str
    item_value: float
    order_date: str


class ApprovalRequest(BaseModel):
    """POST /returns/{thread_id}/approve|reject payload."""

    manager_note: Optional[str] = None


class PhotoResubmitRequest(BaseModel):
    """POST /returns/{thread_id}/photo payload."""

    photo_provided: bool = True
    photo_url: Optional[str] = None