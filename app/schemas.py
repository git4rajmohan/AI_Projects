"""
Pydantic v2 schemas for input, LLM extraction, and final output.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────
class AppointmentIntent(str, Enum):
    schedule = "schedule"
    reschedule = "reschedule"
    cancel = "cancel"
    inquiry = "inquiry"


class ExecutionStatus(str, Enum):
    confirmed = "confirmed"
    no_availability = "no_availability"
    cancelled = "cancelled"
    error = "error"


# ── Input ─────────────────────────────────────────────────────────────────────
class AppointmentRequest(BaseModel):
    """Inbound request from the API consumer."""

    raw_text: str = Field(
        ...,
        description="Raw natural-language text (email, SMS, web form) containing the scheduling request.",
        min_length=1,
    )
    channel: str = Field(
        default="web",
        description="Origin channel: email, sms, web, phone.",
    )


# ── LLM Extraction Output ─────────────────────────────────────────────────────
class ExtractedAppointment(BaseModel):
    """Structured data extracted from raw text by the LLM."""

    intent: AppointmentIntent = Field(
        ...,
        description="The patient's intent: schedule, reschedule, cancel, or inquiry.",
    )
    patient_name: Optional[str] = Field(
        None,
        description="Full name of the patient/client, if mentioned.",
    )
    department: Optional[str] = Field(
        None,
        description="Medical department or service (e.g., cardiology, dermatology).",
    )
    preferred_datetime: Optional[datetime] = Field(
        None,
        description="Requested date and time in ISO 8601 format.",
    )
    contact_phone: Optional[str] = Field(
        None,
        description="Phone number for SMS confirmation, if provided.",
    )
    contact_email: Optional[str] = Field(
        None,
        description="Email address, if provided.",
    )
    notes: Optional[str] = Field(
        None,
        description="Any additional context or special requests.",
    )


# ── Calendar ──────────────────────────────────────────────────────────────────
class CalendarSlot(BaseModel):
    """A single calendar slot with availability status."""

    datetime: datetime
    available: bool


# ── Final Output ──────────────────────────────────────────────────────────────
class ExecutionSummary(BaseModel):
    """Final structured response returned to the API consumer."""

    status: ExecutionStatus = Field(
        ...,
        description="Outcome: confirmed, no_availability, cancelled, or error.",
    )
    extracted: ExtractedAppointment = Field(
        ...,
        description="The structured data extracted from the input text.",
    )
    scheduled_datetime: Optional[datetime] = Field(
        None,
        description="The confirmed appointment datetime, if booked.",
    )
    confirmation_message_sid: Optional[str] = Field(
        None,
        description="Twilio (or mock) message SID for the SMS confirmation.",
    )
    message: str = Field(
        ...,
        description="Human-readable summary of what happened.",
    )


# ── Conversational Chat ───────────────────────────────────────────────────────
class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: ChatRole
    content: str


class ConversationState(str, Enum):
    """Tracks where we are in the booking conversation."""

    greeting = "greeting"
    collecting_info = "collecting_info"
    checking_availability = "checking_availability"
    suggesting_alternatives = "suggesting_alternatives"
    confirming = "confirming"
    completed = "completed"
    cancelled = "cancelled"


class ChatRequest(BaseModel):
    """Inbound chat request — user's message + session ID."""

    message: str = Field(
        ...,
        description="The user's message in the conversation.",
        min_length=1,
    )
    session_id: str = Field(
        default="default",
        description="Session identifier to maintain conversation state.",
    )


class ChatResponse(BaseModel):
    """Bot's response in the conversation."""

    reply: str = Field(
        ...,
        description="The bot's reply message to display to the user.",
    )
    session_id: str = Field(
        ...,
        description="Session identifier for continuity.",
    )
    state: ConversationState = Field(
        default=ConversationState.greeting,
        description="Current conversation state.",
    )
    extracted: Optional[ExtractedAppointment] = Field(
        None,
        description="Appointment details extracted so far (if any).",
    )
    scheduled_datetime: Optional[datetime] = Field(
        None,
        description="The confirmed appointment datetime, if booked.",
    )
    confirmation_message_sid: Optional[str] = Field(
        None,
        description="SMS message SID if confirmation was sent.",
    )
    suggested_slots: list[str] = Field(
        default_factory=list,
        description="Alternative slots suggested when requested time is unavailable.",
    )