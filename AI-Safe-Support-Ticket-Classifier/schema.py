from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class IssueCategory(str, Enum):
    ORDER = "order_issue"
    PAYMENT = "payment_issue"
    DELIVERY = "delivery_issue"
    PRODUCT = "product_issue"
    ACCOUNT = "account_issue"
    REFUND = "refund_request"
    OTHER = "other"


class TeamOwner(str, Enum):
    FULFILLMENT = "fulfillment_team"
    PAYMENTS = "payments_team"
    LOGISTICS = "logistics_team"
    CUSTOMER_SUPPORT = "customer_support"
    TECH = "tech_team"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    ANGRY = "angry"


class TicketClassification(BaseModel):
    issue_category: IssueCategory
    assigned_team: TeamOwner
    priority: Priority
    user_sentiment: Sentiment
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="One line explanation of classification")
    requires_human_review: bool


class TicketState(BaseModel):
    """LangGraph state passed between nodes."""
    raw_ticket: str
    channel: str = "web_form"
    redacted_ticket: Optional[str] = None
    classification: Optional[TicketClassification] = None
    validation_status: Optional[str] = None  # "pass" | "fail"
    cost_info: Optional[dict] = None
    error: Optional[str] = None
    pii_detected: bool = False
    prompt_version: Optional[str] = None
    injection_blocked: bool = False
