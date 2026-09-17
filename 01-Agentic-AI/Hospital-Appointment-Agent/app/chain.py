"""
LangChain LCEL pipeline — extraction chain + appointment orchestrator.

Pipeline:
    raw_text → [prompt | llm | parser] → ExtractedAppointment
             → calendar check → SMS confirmation → ExecutionSummary

Also provides a conversational chat engine for multi-turn booking.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import settings
from .schemas import (
    AppointmentIntent,
    AppointmentRequest,
    CalendarSlot,
    ChatRequest,
    ChatResponse,
    ConversationState,
    ExecutionStatus,
    ExecutionSummary,
    ExtractedAppointment,
)
from .services import calendar_service, sms_service

logger = logging.getLogger(__name__)


# ── LLM ───────────────────────────────────────────────────────────────────────
def _get_llm() -> ChatOpenAI:
    """Create a ChatOpenAI instance pointed at the local Ollama cloud proxy."""
    return ChatOpenAI(
        model=settings.ollama_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.1,  # Low temperature for deterministic extraction
        max_tokens=1024,
    )


# ── Prompt ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a medical appointment scheduling assistant.

Your job is to extract structured appointment information from raw natural-language \
text (which may come from email, SMS, or web forms).

Extract the following fields:
- intent: One of "schedule", "reschedule", "cancel", or "inquiry".
- patient_name: The full name of the patient/client, if mentioned.
- department: The medical department or service requested (e.g., cardiology, dermatology).
- preferred_datetime: The requested date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
  If the user says "tomorrow", "next Monday", etc., resolve it relative to today's date.
  If no specific time is given, use 09:00 as default.
- contact_phone: Phone number for SMS confirmation, if provided.
- contact_email: Email address, if provided.
- notes: Any additional context, special requests, or relevant details.

Rules:
- If a field is not mentioned in the text, set it to null.
- Be conservative — only extract what is explicitly stated or directly implied.
- For dates, always use ISO 8601 format.
- Phone numbers should include country code if available.

{format_instructions}
"""

HUMAN_PROMPT = """\
Raw input text:
{raw_text}
"""


def _build_chain():
    """Build the LCEL extraction chain: prompt | llm | parser."""
    llm = _get_llm()
    parser = PydanticOutputParser(pydantic_object=ExtractedAppointment)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", HUMAN_PROMPT),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    return prompt | llm | parser, parser


# ── Orchestrator ──────────────────────────────────────────────────────────────
def process_appointment_request(request: AppointmentRequest) -> ExecutionSummary:
    """
    Full pipeline: extract → calendar check → SMS → summary.

    Args:
        request: The inbound AppointmentRequest with raw_text.

    Returns:
        ExecutionSummary with the final status and details.
    """
    logger.info(f"Processing appointment request (channel={request.channel})")
    logger.info(f"Raw text: {request.raw_text[:200]}...")

    # Step 1: Extract structured data via LLM
    try:
        chain, parser = _build_chain()
        extracted: ExtractedAppointment = chain.invoke(
            {"raw_text": request.raw_text}
        )
        logger.info(f"Extraction complete: intent={extracted.intent.value}, "
                     f"patient={extracted.patient_name}, "
                     f"dept={extracted.department}, "
                     f"datetime={extracted.preferred_datetime}")
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return ExecutionSummary(
            status=ExecutionStatus.error,
            extracted=ExtractedAppointment(intent=AppointmentIntent.inquiry),
            message=f"LLM extraction failed: {e}",
        )

    # Step 2: Handle based on intent
    if extracted.intent == AppointmentIntent.cancel:
        return ExecutionSummary(
            status=ExecutionStatus.cancelled,
            extracted=extracted,
            message=f"Appointment cancellation processed for {extracted.patient_name or 'patient'}.",
        )

    if extracted.intent == AppointmentIntent.inquiry:
        return ExecutionSummary(
            status=ExecutionStatus.confirmed,
            extracted=extracted,
            message=f"Inquiry processed for {extracted.patient_name or 'patient'}. "
                    f"Department: {extracted.department or 'general'}.",
        )

    # Step 3: Schedule / Reschedule — check calendar
    if extracted.preferred_datetime is None:
        return ExecutionSummary(
            status=ExecutionStatus.error,
            extracted=extracted,
            message="No preferred datetime extracted — cannot check availability.",
        )

    is_available = calendar_service.check_availability(extracted.preferred_datetime)

    if is_available:
        scheduled_dt = extracted.preferred_datetime
    else:
        # Find next available slot
        scheduled_dt = calendar_service.find_next_available(extracted.preferred_datetime)
        if scheduled_dt is None:
            return ExecutionSummary(
                status=ExecutionStatus.no_availability,
                extracted=extracted,
                message="No available slots found within the next 7 days.",
            )

    # Step 4: Send SMS confirmation
    phone = extracted.contact_phone or ""
    sms_body = (
        f"Appointment confirmed for {extracted.patient_name or 'you'} "
        f"with {extracted.department or 'General Medicine'} "
        f"on {scheduled_dt.strftime('%Y-%m-%d at %H:%M')}. "
        f"Reply YES to confirm or call to reschedule."
    )
    message_sid = sms_service.send_confirmation(phone, sms_body)

    # Step 4b: Record the booking in the calendar
    calendar_service.book_slot(
        dt=scheduled_dt,
        patient_name=extracted.patient_name or "Unknown",
        department=extracted.department or "General",
        contact_phone=phone,
        sms_sid=message_sid,
    )

    # Step 5: Assemble summary
    status = ExecutionStatus.confirmed
    if not is_available:
        msg = (
            f"Requested slot unavailable. Booked next available: "
            f"{scheduled_dt.strftime('%Y-%m-%d at %H:%M')}. "
            f"SMS sent (SID: {message_sid})."
        )
    else:
        msg = (
            f"Appointment confirmed for {scheduled_dt.strftime('%Y-%m-%d at %H:%M')}. "
            f"SMS sent (SID: {message_sid})."
        )

    return ExecutionSummary(
        status=status,
        extracted=extracted,
        scheduled_datetime=scheduled_dt,
        confirmation_message_sid=message_sid,
        message=msg,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONAL CHAT ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

CHAT_SYSTEM_PROMPT = """\
You are a friendly medical appointment scheduling assistant bot named "Scheduler Bot".

Your job is to have a natural conversation with the patient to collect all the \
information needed to book, reschedule, or cancel an appointment.

You must collect the following information before booking a NEW appointment:
1. Patient name (required)
2. Department / service needed (required — e.g., cardiology, dermatology, general medicine)
3. Preferred date and time (required — help them pick a weekday, business hours 09:00–17:00)
4. Contact phone number (required for SMS confirmation)

For RESCHEDULE requests:
- The patient already has an appointment. You need their name to look up the existing booking.
- You do NOT need to ask for the phone number or department again — those are already on file.
- You only need: patient name (to find the booking) + new preferred date and time.
- If there are multiple bookings for the same name, ask which one they want to reschedule.

Conversation guidelines:
- Be warm, concise, and conversational. Ask ONE question at a time.
- If the user provides partial info, acknowledge what you got and ask for what's missing.
- If the user mentions a date but no time, suggest 09:00 as default and ask if that works.
- If the user says "tomorrow", "next Monday", etc., resolve it relative to today's date: {today}
- When you have all required info, tell the user you're checking availability.
- If the requested slot is unavailable, suggest 2-3 alternative slots (next available).
- Once the user agrees to a slot, confirm the booking and tell them an SMS will be sent.
- If the user wants to cancel, acknowledge the cancellation politely.
- Keep responses short — 1-3 sentences max. No bullet points or long lists.

Current conversation state: {state}
Information collected so far: {collected_info}
Suggested alternative slots (if any): {suggested_slots}
"""

CHAT_EXTRACTION_PROMPT = """\
You are an information extraction assistant. Extract appointment details from the \
user's latest message, considering what has already been collected in the conversation.

Already known information:
{existing_info}

User's latest message:
{user_message}

Today's date: {today}

Extract any of these fields that are present or can be inferred:
- intent: schedule, reschedule, cancel, or inquiry
- patient_name: full name
- department: medical department. If the user describes symptoms instead of naming a \
department, infer the most appropriate one. For example: "cold/flu/fever" → "general medicine", \
"chest pain/heart" → "cardiology", "skin rash" → "dermatology", "joint pain/broken bone" → "orthopedics", \
"eye problem" → "ophthalmology", "stomach/digestion" → "gastroenterology", "anxiety/depression" → "psychiatry".
- preferred_datetime: ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
- contact_phone: phone number with country code
- contact_email: email address
- notes: any additional context

Only include fields that are explicitly stated or directly implied. \
For fields not mentioned, output null.

{format_instructions}
"""


# ── In-memory session store ───────────────────────────────────────────────────
class ChatSession:
    """Tracks conversation state for a single user session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: list[dict] = []  # Full conversation history
        self.state: ConversationState = ConversationState.greeting
        self.extracted: ExtractedAppointment = ExtractedAppointment(
            intent=AppointmentIntent.inquiry
        )
        self.scheduled_datetime: Optional[datetime] = None
        self.confirmation_message_sid: Optional[str] = None
        self.suggested_slots: list[str] = []
        self.pending_slot: Optional[datetime] = None  # Slot awaiting user confirmation
        self.reschedule_booking_id: Optional[int] = None  # Booking ID being rescheduled
        self.reschedule_old_dt: Optional[datetime] = None  # Original datetime for reschedule

    def collected_info_summary(self) -> str:
        """Human-readable summary of what's been collected."""
        e = self.extracted
        parts = []
        if e.intent and e.intent.value != "inquiry":
            parts.append(f"intent={e.intent.value}")
        if e.patient_name:
            parts.append(f"name={e.patient_name}")
        if e.department:
            parts.append(f"department={e.department}")
        if e.preferred_datetime:
            parts.append(f"datetime={e.preferred_datetime.isoformat()}")
        if e.contact_phone:
            parts.append(f"phone={e.contact_phone}")
        if e.contact_email:
            parts.append(f"email={e.contact_email}")
        if e.notes:
            parts.append(f"notes={e.notes}")
        return ", ".join(parts) if parts else "nothing yet"


# Global session store (in-memory — fine for single-user dev)
_sessions: dict[str, ChatSession] = {}


def _get_or_create_session(session_id: str) -> ChatSession:
    """Get an existing session or create a new one."""
    if session_id not in _sessions:
        _sessions[session_id] = ChatSession(session_id)
    return _sessions[session_id]


def _extract_from_chat(
    user_message: str,
    existing: ExtractedAppointment,
) -> ExtractedAppointment:
    """
    Use the LLM to extract/update appointment info from the user's latest message,
    merging with already-known information.

    Falls back to a simpler raw-JSON approach if the PydanticOutputParser fails.
    """
    llm = _get_llm()
    parser = PydanticOutputParser(pydantic_object=ExtractedAppointment)

    existing_info = (
        f"intent={existing.intent.value}, "
        f"name={existing.patient_name}, "
        f"department={existing.department}, "
        f"datetime={existing.preferred_datetime}, "
        f"phone={existing.contact_phone}, "
        f"email={existing.contact_email}, "
        f"notes={existing.notes}"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", CHAT_EXTRACTION_PROMPT),
    ]).partial(
        existing_info=existing_info,
        today=datetime.now().strftime("%Y-%m-%d"),
        format_instructions=parser.get_format_instructions(),
    )

    # Try the structured chain first
    try:
        chain = prompt | llm | parser
        new_extracted = chain.invoke({"user_message": user_message})
        return _merge_extracted(existing, new_extracted, user_message)
    except Exception as e:
        logger.warning(f"Chat extraction (structured) failed: {e}")

    # Fallback: ask the LLM directly for JSON, parse manually
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        today_str = datetime.now().strftime("%Y-%m-%d (%A)")
        simple_prompt = (
            f"Today is {today_str}.\n\n"
            f"Extract appointment details from this user message and return as JSON.\n"
            f"Already known: {existing_info}\n\n"
            f'User message: "{user_message}"\n\n'
            f'Return ONLY a JSON object (no markdown, no explanation) with these fields:\n'
            f'  "intent": one of "schedule", "reschedule", "cancel", "inquiry"\n'
            f'  "patient_name": full name or null\n'
            f'  "department": medical department or null\n'
            f'  "preferred_datetime": ISO 8601 like "2026-09-08T10:00:00" or null\n'
            f'  "contact_phone": phone number or null\n'
            f'  "contact_email": email or null\n'
            f'  "notes": any extra context or null\n'
        )

        raw_response = llm.invoke([SystemMessage(content=simple_prompt), HumanMessage(content="Return the JSON now.")])
        raw_text = raw_response.content.strip()
        logger.info(f"Chat extraction fallback raw response: {raw_text[:500]}")

        # Try to extract JSON from the response
        json_data = _extract_json_from_text(raw_text)
        if json_data:
            logger.info(f"Chat extraction fallback parsed JSON: {json_data}")
            new_extracted = _parse_extracted_dict(json_data)
            return _merge_extracted(existing, new_extracted, user_message)
        else:
            logger.warning(f"Chat extraction fallback: could not parse JSON from: {raw_text[:200]}")
    except Exception as e2:
        logger.warning(f"Chat extraction (fallback) failed: {e2}")

    # Last resort: try local symptom inference, otherwise return existing unchanged
    if not existing.department:
        inferred_dept = _infer_department_from_text(user_message)
        if inferred_dept:
            merged = existing.model_copy(deep=True)
            merged.department = inferred_dept
            logger.info(f"Chat extraction: inferred department='{inferred_dept}' from local symptom map")
            return merged

    return existing


def _merge_extracted(
    existing: ExtractedAppointment,
    new: ExtractedAppointment,
    user_message: str = "",
) -> ExtractedAppointment:
    """Merge new extraction into existing, only updating non-null fields."""
    merged = existing.model_copy(deep=True)
    if new.intent:
        merged.intent = new.intent
    if new.patient_name:
        merged.patient_name = new.patient_name
    if new.department:
        merged.department = new.department
    if new.preferred_datetime:
        merged.preferred_datetime = new.preferred_datetime
    if new.contact_phone:
        merged.contact_phone = new.contact_phone
    if new.contact_email:
        merged.contact_email = new.contact_email
    if new.notes:
        merged.notes = new.notes

    # If department is still missing, try local symptom inference from the user message
    if not merged.department and user_message:
        inferred = _infer_department_from_text(user_message)
        if inferred:
            merged.department = inferred
            logger.info(f"Chat extraction: inferred department='{inferred}' from local symptom map")

    # If phone is still missing, try local phone number detection
    if not merged.contact_phone and user_message:
        phone = _extract_phone_from_text(user_message)
        if phone:
            merged.contact_phone = phone
            logger.info(f"Chat extraction: extracted phone='{phone}' from local detection")

    # If patient_name is still missing, try local name detection
    if not merged.patient_name and user_message:
        name = _extract_name_from_text(user_message)
        if name:
            merged.patient_name = name
            logger.info(f"Chat extraction: extracted name='{name}' from local detection")

    # If preferred_datetime is still missing, try local date parsing
    if not merged.preferred_datetime and user_message:
        dt = _extract_datetime_from_text(user_message)
        if dt:
            merged.preferred_datetime = dt
            logger.info(f"Chat extraction: extracted datetime='{dt}' from local detection")

    # Safety net: if the user mentioned a weekday by name but the merged datetime
    # falls on a different weekday, the LLM (or local parser) got the day wrong —
    # fix it by snapping to the correct weekday while keeping the time.
    if merged.preferred_datetime and user_message:
        corrected = _fix_weekday_mismatch(merged.preferred_datetime, user_message)
        if corrected != merged.preferred_datetime:
            logger.info(
                f"Chat extraction: weekday mismatch — LLM said {merged.preferred_datetime} "
                f"but user asked for a different weekday; corrected to {corrected}"
            )
            merged.preferred_datetime = corrected

    return merged


_WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _fix_weekday_mismatch(dt: datetime, user_message: str) -> datetime:
    """
    If the user's message mentions exactly one weekday and the extracted datetime
    falls on a different weekday, snap the date to the correct weekday (keeping
    the time from the extracted datetime). Returns the corrected datetime.
    """
    lower = user_message.lower()
    mentioned = [i for i, wd in enumerate(_WEEKDAY_NAMES) if re.search(rf'\b{wd}\b', lower)]
    if len(mentioned) != 1:
        return dt  # No (or ambiguous) weekday mention — nothing to fix

    target_idx = mentioned[0]
    if dt.weekday() == target_idx:
        return dt  # Already correct

    # Snap the date to the next occurrence of the target weekday, keep the time
    current_idx = dt.weekday()
    days_ahead = (target_idx - current_idx) % 7
    fixed = dt + timedelta(days=days_ahead)
    return fixed.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)


def _extract_json_from_text(text: str) -> Optional[dict]:
    """Try to extract a JSON object from raw LLM text output."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON between { and }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            # Try fixing common issues (trailing commas, single quotes)
            cleaned = match.group()
            cleaned = re.sub(r',\s*}', '}', cleaned)  # trailing comma before }
            cleaned = re.sub(r',\s*]', ']', cleaned)  # trailing comma before ]
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    return None


def _parse_extracted_dict(data: dict) -> ExtractedAppointment:
    """Parse a raw dict into an ExtractedAppointment, handling type coercion."""
    kwargs = {}

    intent_str = data.get("intent")
    if intent_str and isinstance(intent_str, str):
        try:
            kwargs["intent"] = AppointmentIntent(intent_str.lower().strip())
        except ValueError:
            pass

    for field in ["patient_name", "department", "contact_phone", "contact_email", "notes"]:
        val = data.get(field)
        if val and isinstance(val, str) and val.strip().lower() not in ("null", "none", ""):
            kwargs[field] = val.strip()

    dt_str = data.get("preferred_datetime")
    if dt_str and isinstance(dt_str, str) and dt_str.strip().lower() not in ("null", "none", ""):
        try:
            kwargs["preferred_datetime"] = datetime.fromisoformat(dt_str.strip().replace("Z", ""))
        except ValueError:
            pass

    return ExtractedAppointment(**kwargs)


def _generate_chat_reply(
    session: ChatSession,
    user_message: str,
) -> str:
    """Generate a conversational reply using the LLM with full context."""
    llm = _get_llm()

    # Build the conversation history for the LLM
    history_msgs = [{"role": "system", "content": _build_system_msg(session)}]
    for msg in session.messages[-10:]:  # Last 10 messages for context
        history_msgs.append(msg)
    history_msgs.append({"role": "user", "content": user_message})

    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

    lc_messages = []
    for m in history_msgs:
        if m["role"] == "system":
            lc_messages.append(SystemMessage(content=m["content"]))
        elif m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        else:
            lc_messages.append(AIMessage(content=m["content"]))

    try:
        response = llm.invoke(lc_messages)
        return response.content.strip()
    except Exception as e:
        logger.error(f"Chat reply generation failed: {e}")
        return (
            "I'm having trouble connecting to my brain right now. "
            "Please try again in a moment."
        )


def _build_system_msg(session: ChatSession) -> str:
    """Build the system prompt with current session context."""
    return CHAT_SYSTEM_PROMPT.format(
        today=datetime.now().strftime("%Y-%m-%d (%A)"),
        state=session.state.value,
        collected_info=session.collected_info_summary(),
        suggested_slots=", ".join(session.suggested_slots) if session.suggested_slots else "none",
    )


def _find_alternative_slots(dt: datetime, count: int = 3) -> list[datetime]:
    """Find the next `count` available slots after the given datetime."""
    slots = []
    candidate = dt.replace(minute=0, second=0, microsecond=0)
    if candidate <= dt:
        candidate += timedelta(hours=1)

    for _ in range(168):  # Search up to 7 days
        if calendar_service.check_availability(candidate):
            slots.append(candidate)
            if len(slots) >= count:
                break
        candidate += timedelta(hours=1)

    return slots


def _is_info_complete(ext: ExtractedAppointment) -> bool:
    """Check if we have all required fields to attempt booking."""
    return (
        ext.patient_name is not None
        and ext.department is not None
        and ext.preferred_datetime is not None
        and ext.contact_phone is not None
    )


def _missing_fields(ext: ExtractedAppointment) -> list[str]:
    """Return list of missing required field names."""
    missing = []
    if not ext.patient_name:
        missing.append("patient name")
    if not ext.department:
        missing.append("department")
    if not ext.preferred_datetime:
        missing.append("preferred date and time")
    if not ext.contact_phone:
        missing.append("contact phone number")
    return missing


def _missing_fields_for_reschedule(ext: ExtractedAppointment) -> list[str]:
    """For reschedule, only need patient name + new datetime."""
    missing = []
    if not ext.patient_name:
        missing.append("patient name")
    if not ext.preferred_datetime:
        missing.append("new preferred date and time")
    return missing


def _is_reschedule_info_complete(ext: ExtractedAppointment) -> bool:
    """Check if we have enough info to attempt a reschedule."""
    return ext.patient_name is not None and ext.preferred_datetime is not None


# ── Symptom → Department mapping (fallback when LLM doesn't infer) ─────────────
SYMPTOM_DEPARTMENT_MAP: dict[str, str] = {
    # General medicine
    "cold": "general medicine", "flu": "general medicine", "fever": "general medicine",
    "cough": "general medicine", "sore throat": "general medicine", "runny nose": "general medicine",
    "sneezing": "general medicine", "congestion": "general medicine", "headache": "general medicine",
    "tired": "general medicine", "fatigue": "general medicine", "body ache": "general medicine",
    "infection": "general medicine", "nausea": "general medicine",
    "vomit": "general medicine", "vomiting": "general medicine", "vomitting": "general medicine",
    "throw up": "general medicine", "throwing up": "general medicine",
    "chills": "general medicine", "shivering": "general medicine", "sweating": "general medicine",
    "weakness": "general medicine", "dizzy": "general medicine", "fainting": "general medicine",
    "allergy": "general medicine", "allergies": "general medicine", "sneez": "general medicine",
    "wheezing": "general medicine", "phlegm": "general medicine", "mucus": "general medicine",
    "body pain": "general medicine", "muscle pain": "general medicine", "malaise": "general medicine",
    "not feeling well": "general medicine", "feeling sick": "general medicine", "sick": "general medicine",
    "ill": "general medicine", "unwell": "general medicine", "symptom": "general medicine",
    "symptoms": "general medicine", "feeling bad": "general medicine",
    # Cardiology
    "chest pain": "cardiology", "heart": "cardiology", "palpitation": "cardiology",
    "shortness of breath": "cardiology", "blood pressure": "cardiology",
    "chest tightness": "cardiology", "chest pressure": "cardiology",
    "irregular heartbeat": "cardiology", "heart palpitation": "cardiology",
    "high blood pressure": "cardiology", "low blood pressure": "cardiology",
    # Dermatology
    "skin": "dermatology", "rash": "dermatology", "acne": "dermatology",
    "itch": "dermatology", "eczema": "dermatology", "mole": "dermatology",
    "hives": "dermatology", "psoriasis": "dermatology",
    "dry skin": "dermatology", "skin rash": "dermatology", "itching": "dermatology",
    "skin infection": "dermatology", "wart": "dermatology", "blister": "dermatology",
    "sunburn": "dermatology", "rosacea": "dermatology", "skin cancer": "dermatology",
    # Orthopedics
    "joint": "orthopedics", "bone": "orthopedics", "knee": "orthopedics",
    "back pain": "orthopedics", "fracture": "orthopedics", "sprain": "orthopedics",
    "arthritis": "orthopedics", "shoulder": "orthopedics", "hip": "orthopedics",
    "neck pain": "orthopedics", "spine": "orthopedics", "muscle": "orthopedics",
    "leg pain": "orthopedics", "arm pain": "orthopedics", "elbow": "orthopedics",
    "wrist": "orthopedics", "ankle": "orthopedics", "sciatica": "orthopedics",
    "slipped disc": "orthopedics", "herniated disc": "orthopedics",
    # Ophthalmology
    "eye": "ophthalmology", "vision": "ophthalmology", "blurred": "ophthalmology",
    "glasses": "ophthalmology", "cataract": "ophthalmology",
    "eye pain": "ophthalmology", "red eye": "ophthalmology", "dry eye": "ophthalmology",
    "eye infection": "ophthalmology", "conjunctivitis": "ophthalmology",
    "pink eye": "ophthalmology", "stye": "ophthalmology", "glaucoma": "ophthalmology",
    # Gastroenterology
    "stomach": "gastroenterology", "digestion": "gastroenterology", "ulcer": "gastroenterology",
    "bowel": "gastroenterology", "diarrhea": "gastroenterology", "constipation": "gastroenterology",
    "acid reflux": "gastroenterology", "heartburn": "gastroenterology",
    "stomach pain": "gastroenterology", "abdominal pain": "gastroenterology", "belly pain": "gastroenterology",
    "bloating": "gastroenterology", "gas": "gastroenterology", "indigestion": "gastroenterology",
    "stomach ache": "gastroenterology", "tummy": "gastroenterology", "gallbladder": "gastroenterology",
    "liver": "gastroenterology", "ibs": "gastroenterology", "crohn": "gastroenterology",
    "colitis": "gastroenterology", "hemorrhoid": "gastroenterology", "piles": "gastroenterology",
    # Psychiatry
    "anxiety": "psychiatry", "depression": "psychiatry", "stress": "psychiatry",
    "mental health": "psychiatry", "panic": "psychiatry", "insomnia": "psychiatry",
    "sad": "psychiatry", "mood": "psychiatry", "bipolar": "psychiatry",
    "ocd": "psychiatry", "trauma": "psychiatry", "ptsd": "psychiatry",
    "can't sleep": "psychiatry", "cant sleep": "psychiatry", "sleep problem": "psychiatry",
    # ENT
    "ear": "ent", "nose": "ent", "throat": "ent", "sinus": "ent", "hearing": "ent",
    "tinnitus": "ent", "vertigo": "ent",
    "earache": "ent", "ear pain": "ent", "ear infection": "ent",
    "sinusitis": "ent", "tonsil": "ent", "laryngitis": "ent",
    "nosebleed": "ent", "blocked nose": "ent", "stuffy nose": "ent",
    # Neurology
    "migraine": "neurology", "seizure": "neurology", "numbness": "neurology",
    "dizziness": "neurology", "neuropathy": "neurology",
    "tingling": "neurology", "tremor": "neurology", "memory loss": "neurology",
    "forgetfulness": "neurology", "concussion": "neurology", "stroke": "neurology",
    "epilepsy": "neurology", "parkinson": "neurology", "ms": "neurology",
    # Dental
    "tooth": "dental", "teeth": "dental", "gum": "dental", "cavity": "dental",
    "toothache": "dental", "tooth pain": "dental", "wisdom tooth": "dental",
    "root canal": "dental", "gingivitis": "dental", "braces": "dental",
    "denture": "dental", "teeth cleaning": "dental", "chipped tooth": "dental",
    # Urology
    "urine": "urology", "urinary": "urology", "bladder": "urology", "kidney": "urology",
    "prostate": "urology", "kidney stone": "urology", "uti": "urology",
    "blood in urine": "urology", "frequent urination": "urology",
    # Pulmonology
    "asthma": "pulmonology", "pneumonia": "pulmonology", "bronchitis": "pulmonology",
    "lung": "pulmonology", "breathing problem": "pulmonology", "copd": "pulmonology",
    # Endocrinology
    "diabetes": "endocrinology", "thyroid": "endocrinology", "hormone": "endocrinology",
    "blood sugar": "endocrinology", "hyperthyroid": "endocrinology", "hypothyroid": "endocrinology",
    # Gynecology
    "pregnancy": "gynecology", "pregnant": "gynecology", "menstrual": "gynecology",
    "period": "gynecology", "gynecological": "gynecology", "pap smear": "gynecology",
    "menopause": "gynecology", "ovary": "gynecology", "fertility": "gynecology",
    # Pediatrics
    "child": "pediatrics", "baby": "pediatrics", "infant": "pediatrics",
    "kid": "pediatrics", "toddler": "pediatrics", "newborn": "pediatrics",
}


def _infer_department_from_text(text: str) -> Optional[str]:
    """Try to infer a department from symptoms/keywords in the user's text."""
    lower = text.lower()
    for symptom, dept in SYMPTOM_DEPARTMENT_MAP.items():
        if symptom in lower:
            return dept
    return None


def _extract_phone_from_text(text: str) -> Optional[str]:
    """
    Try to extract a phone number from the user's text.
    Handles various formats: +15551234567, 525652256, (555) 123-4567, etc.
    """
    # Pattern 1: International format with + and country code
    match = re.search(r'\+\d{1,3}[\s-]?\d{3,14}', text)
    if match:
        return re.sub(r'[\s-]', '', match.group())

    # Pattern 2: US format (xxx) xxx-xxxx
    match = re.search(r'\(\d{3}\)\s*\d{3}[\s-]?\d{4}', text)
    if match:
        return re.sub(r'[\s\(\)-]', '', match.group())

    # Pattern 3: Just digits — at least 7 digits in a row (not part of a date)
    # Avoid matching dates like "2026-09-08" or times like "10:00"
    # Look for digit sequences that are 7-15 digits long, possibly with spaces/dashes
    for m in re.finditer(r'(?<!\d)(\d[\d\s-]{5,}\d)(?!\d)', text):
        digits_only = re.sub(r'[\s-]', '', m.group())
        # Skip if it looks like a date (contains - between 4-digit year)
        if re.match(r'^\d{4}-\d{2}-\d{2}', digits_only):
            continue
        # Skip if it's exactly 4 digits (could be a year)
        if len(digits_only) == 4:
            continue
        # Must be 7-15 digits to be a phone number
        if 7 <= len(digits_only) <= 15:
            return digits_only

    return None


def _extract_name_from_text(text: str) -> Optional[str]:
    """
    Try to extract a person's name from the user's text.
    Looks for patterns like "my name is X", "I am X", "this is X", or just "X" (2+ capitalized words).
    """
    lower = text.lower().strip()

    # ── Greeting / common phrase blacklist — never treat these as names ──
    GREETING_PHRASES = {
        "hi there", "hello there", "hey there", "hi", "hello", "hey", "hiya",
        "howdy", "greetings", "good morning", "good afternoon", "good evening",
        "good night", "what's up", "whats up", "sup", "yo", "hi hi", "hey hey",
        "hello hello", "hi hello", "hello hi", "hey you", "hi you", "hello you",
        "yes", "no", "ok", "okay", "sure", "nope", "yeah", "yep", "nah",
        "thank you", "thanks", "thank", "thx", "ty", "cool", "nice", "great",
        "fine", "good", "bad", "help", "help me", "please", "sorry",
        "i don't know", "i dont know", "not sure", "idk", "maybe",
        "what", "why", "how", "when", "where", "who",
        "test", "testing", "asdf", "qwerty",
    }
    if lower in GREETING_PHRASES:
        return None

    # Also check if the text starts with a greeting followed by other words
    GREETING_STARTERS = {"hi", "hello", "hey", "howdy", "yo", "sup", "hiya", "greetings"}
    first_word = lower.split()[0] if lower.split() else ""
    if first_word in GREETING_STARTERS and len(lower.split()) <= 3:
        # "hi there", "hello everyone", "hey what's up" — not a name
        return None

    # Pattern: "my name is X", "name is X", "i am X", "this is X"
    patterns = [
        r'(?:my name is|name is|i am|i\'m|this is|it\'s)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'(?:my name is|name is|i am|i\'m|this is|it\'s)\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*[A-Z][a-z]+)*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Title case it properly
            return " ".join(w.capitalize() for w in name.split())

    # Pattern: just 2+ capitalized words (e.g., "John william", "Adam Sandler")
    words = text.strip().split()
    if 2 <= len(words) <= 4:
        # Check if all words look like name parts (start with letter, no numbers)
        if all(re.match(r'^[A-Za-z]+$', w) for w in words):
            # Extra check: skip if any word is a common greeting/keyword
            word_set = {w.lower() for w in words}
            if word_set & GREETING_STARTERS:
                return None
            return " ".join(w.capitalize() for w in words)

    return None


# ── Local date/time parsing for vague expressions ─────────────────────────────
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _extract_datetime_from_text(text: str) -> Optional[datetime]:
    """
    Try to extract a datetime from the user's text using local parsing.
    Handles various formats:
      - "September 9 at 11am" / "Sep 9 at 11:00"
      - "on the 16th" / "after the 15th" / "any day after 15"
      - "tomorrow" / "next Monday"
      - "2026-09-09 at 11:00"
    """
    now = datetime.now()
    lower = text.lower().strip()

    # ── "tomorrow" ──
    if "tomorrow" in lower:
        tmrw = now + timedelta(days=1)
        hour = _extract_hour(lower)
        return tmrw.replace(hour=hour, minute=0, second=0, microsecond=0)

    # ── "next <weekday>" ──
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, wd in enumerate(weekdays):
        if f"next {wd}" in lower or f"this {wd}" in lower:
            days_ahead = (i - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = now + timedelta(days=days_ahead)
            hour = _extract_hour(lower)
            return target.replace(hour=hour, minute=0, second=0, microsecond=0)

    # ── Bare "<weekday>" (e.g. "wednesday 9am", "friday at 3pm") ──
    # Resolve to the NEXT occurrence of that weekday (today if it matches).
    for i, wd in enumerate(weekdays):
        if re.search(rf'\b{wd}\b', lower):
            days_ahead = (i - now.weekday()) % 7
            target = now + timedelta(days=days_ahead)
            hour = _extract_hour(lower)
            return target.replace(hour=hour, minute=0, second=0, microsecond=0)

    # ── "after the 15th" / "any day after 15" / "on the 16th" ──
    # Extract a day number with optional "after" / "on the" prefix
    after_match = re.search(r'(?:after|on|by|from)\s*(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?', lower)
    if after_match:
        day_num = int(after_match.group(1))
        # Determine the month — use current month, or next month if day has passed
        month = now.month
        year = now.year
        if day_num <= now.day and "after" in lower:
            # "after 15" when today is the 15th or later → start from tomorrow
            target_day = day_num + 1 if day_num >= now.day else day_num
            if target_day > 28:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                # Find first weekday in the new month
                target_day = 1
            elif day_num < now.day:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                target_day = day_num
        elif "after" in lower:
            target_day = day_num + 1
        else:
            target_day = day_num

        # Find the next available weekday on or after target_day
        try:
            candidate = datetime(year, month, target_day, _extract_hour(lower), 0, 0)
        except ValueError:
            return None

        # If "after", skip to next day if candidate is weekend
        # Find first weekday on or after the target day
        for _ in range(10):
            if candidate.weekday() < 5:  # Weekday
                return candidate
            candidate += timedelta(days=1)

    # ── "September 9 at 11am" / "Sep 9 at 11:00" ──
    month_match = re.search(
        r'(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|'
        r'august|aug|september|sep|sept|october|oct|november|nov|december|dec)\s+(\d{1,2})',
        lower
    )
    if month_match:
        month = _MONTHS.get(month_match.group(1))
        day = int(month_match.group(2))
        year = now.year
        if month < now.month or (month == now.month and day < now.day):
            year += 1
        hour = _extract_hour(lower)
        try:
            return datetime(year, month, day, hour, 0, 0)
        except ValueError:
            return None

    # ── ISO format "2026-09-09 at 11:00" ──
    iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})\s*(?:at\s+)?(\d{1,2})?(?::(\d{2}))?', text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        h = int(iso_match.group(4)) if iso_match.group(4) else 9
        mi = int(iso_match.group(5)) if iso_match.group(5) else 0
        try:
            return datetime(y, m, d, h, mi)
        except ValueError:
            return None

    return None


def _extract_hour_preference(text: str) -> Optional[int]:
    """
    Extract just an hour preference from text when no date is specified.
    Handles: "15 time", "3pm any day", "at 15:00", "15:00 any day",
             "fix 15 time of any day", "any day at 3pm"
    Returns the hour (0-23) or None.

    Only accepts hours anchored to time keywords (at/time/fix/am/pm/o'clock/
    hour/slot) so bare day numbers are never mistaken for hours.
    """
    lower = text.lower().strip()

    # 1. Explicit am/pm takes priority: "3pm any day", "any day at 10am"
    ampm_match = re.search(r'\b(\d{1,2})\s*(am|pm)\b', lower)
    if ampm_match:
        hour = int(ampm_match.group(1))
        if ampm_match.group(2) == "pm" and hour < 12:
            hour += 12
        if ampm_match.group(2) == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return hour

    # 2. Hour anchored by time keywords: "15 time", "at 15", "fix 15 time"
    patterns = [
        r'(?:at|time|fix)\s*(\d{1,2})(?::00)?(?:\s*(?:time|o\'clock))?',
        r'(\d{1,2})(?::00)?\s*(?:o\'clock|hour|slot)\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            hour = int(match.group(1))
            if 0 <= hour <= 23:
                return hour

    return None


# ── Off-topic detection ───────────────────────────────────────────────────────
# Keywords that indicate the user is asking something unrelated to appointments
_OFF_TOPIC_KEYWORDS = {
    # General questions
    "weather", "news", "joke", "recipe", "cook", "movie", "music", "song",
    "game", "play", "sport", "football", "basketball", "cricket", "soccer",
    "stock", "market", "crypto", "bitcoin", "money", "invest",
    "code", "programming", "python", "javascript", "java", "computer",
    "ai", "chatgpt", "gpt", "language model", "write me", "write a",
    "translate", "math", "calculate", "history", "geography",
    "president", "politics", "election", "war",
    # Questions about the bot itself
    "who are you", "what are you", "how do you work", "what can you do",
    "are you a robot", "are you ai", "are you human",
}

# Keywords that ARE related to appointments/hospital — even if they look like questions
_APPOINTMENT_KEYWORDS = {
    "appointment", "book", "schedule", "reschedule", "cancel", "doctor",
    "hospital", "clinic", "medical", "health", "sick", "ill", "pain",
    "fever", "cold", "flu", "cough", "headache", "department", "cardiology",
    "dermatology", "orthopedics", "general medicine", "checkup", "check up",
    "visit", "consultation", "specialist", "physician", "nurse",
    "date", "time", "slot", "available", "availability", "calendar",
    "phone", "number", "name", "sms", "confirmation", "confirm",
    "tomorrow", "today", "monday", "tuesday", "wednesday", "thursday",
    "friday", "week", "month", "september", "october",
    "morning", "afternoon", "evening", "am", "pm",
    "yes", "no", "ok", "sure", "cancel", "inquiry",
    "symptom", "rash", "stomach", "chest", "back", "eye", "ear", "throat",
    "skin", "joint", "bone", "tooth", "teeth", "anxiety", "depression",
}


def _is_off_topic(text: str, ext: ExtractedAppointment) -> bool:
    """
    Detect if the user's message is off-topic (unrelated to appointment booking).
    Only triggers during collecting_info state when no new info was extracted.
    """
    lower = text.lower().strip()

    # Short messages (1-3 words) are likely attempts to answer — not off-topic
    if len(lower.split()) <= 3:
        return False

    # If the message contains strong off-topic keywords, it IS off-topic
    # (these override appointment keywords — "weather today" is still off-topic)
    strong_off_topic = {
        "weather", "news", "joke", "recipe", "cook", "movie", "music", "song",
        "game", "play", "sport", "football", "basketball", "cricket", "soccer",
        "stock", "market", "crypto", "bitcoin", "money", "invest",
        "code", "programming", "python", "javascript", "java", "computer",
        "ai", "chatgpt", "gpt", "language model", "write me", "write a",
        "translate", "math", "calculate", "history", "geography",
        "president", "politics", "election", "war",
    }
    if any(kw in lower for kw in strong_off_topic):
        return True

    # If the message contains appointment-related keywords, it's not off-topic
    if any(kw in lower for kw in _APPOINTMENT_KEYWORDS):
        return False

    # If the message is a question (starts with who/what/why/how/when/where/can you/do you)
    question_starters = ("who ", "what ", "why ", "how ", "when ", "where ", "can you ",
                         "do you ", "could you ", "would you ", "tell me ", "explain ",
                         "what's ", "whats ")
    if any(lower.startswith(q) for q in question_starters):
        return True

    # If the message is long (> 20 words) and contains no appointment keywords,
    # it's likely off-topic
    if len(lower.split()) > 20:
        return True

    return False


def _extract_time_only(text: str) -> Optional[int]:
    """
    Extract ONLY a time-of-day from text (no date).
    Handles: "3pm", "at 15:00", "15:00", "10am", "11 o'clock"
    Returns the hour (0-23) or None if no time expression is found.
    """
    lower = text.lower()

    # 1. Explicit am/pm: "3pm", "10:30am", "10 am"
    match = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', lower)
    if match:
        hour = int(match.group(1))
        if match.group(3) == "pm" and hour < 12:
            hour += 12
        if match.group(3) == "am" and hour == 12:
            hour = 0
        return hour

    # 2. Hour introduced by "at": "at 15", "at 15:00"
    match = re.search(r'\bat\s+(\d{1,2})(?::(\d{2}))?\b', lower)
    if match:
        return int(match.group(1))

    # 3. Plain "15:00" style (with colon)
    match = re.search(r'\b(\d{1,2}):(\d{2})\b', lower)
    if match:
        return int(match.group(1))

    # 4. "11 o'clock"
    match = re.search(r"\b(\d{1,2})\s*o'?clock\b", lower)
    if match:
        return int(match.group(1))

    return None


def _extract_hour(text: str) -> int:
    """
    Extract an hour from text, handling am/pm.

    Prefers explicit time expressions (e.g. "10am", "at 15:00", "3 o'clock")
    over bare numbers, so day numbers like "September 21" are never mistaken
    for hours (21:00 → outside business hours → false "not available").
    """
    hour = _extract_time_only(text)
    return hour if hour is not None else 9  # Default hour


def _deterministic_collecting_reply(ext: ExtractedAppointment, session: "ChatSession" = None) -> str:
    """
    Generate a deterministic reply that asks for the next missing field.
    This replaces the LLM-generated reply to prevent the bot from
    improvising or asking for things out of order.
    """
    missing = _missing_fields(ext)

    if not missing:
        # Shouldn't happen, but just in case
        return "Let me check availability for your request."

    # Ask for the first missing field, acknowledging what we already have
    ack_parts = []
    if ext.patient_name:
        ack_parts.append(f"Great, {ext.patient_name}!")
    if ext.department:
        ack_parts.append(f"Department: {ext.department}. ✓")

    ack = " ".join(ack_parts) if ack_parts else "Got it."

    next_field = missing[0]
    if next_field == "patient name":
        return f"{ack} May I have your full name, please?"
    elif next_field == "department":
        # Check if the user described symptoms — we can suggest a department
        # by looking at the last few user messages in the session
        recent_user_text = ""
        for m in reversed(session.messages[-4:]):
            if m.get("role") == "user":
                recent_user_text += " " + m.get("content", "")
        inferred = _infer_department_from_text(recent_user_text)
        if inferred:
            return (
                f"{ack} Based on what you've described, I'd suggest the "
                f"**{inferred.title()}** department. Does that sound right, "
                f"or would you prefer a different one?"
            )
        return f"{ack} Which department or service do you need? (e.g., cardiology, dermatology, general medicine)"
    elif next_field == "preferred date and time":
        return f"{ack} What date and time would you prefer? (Business hours are 09:00–17:00, weekdays only.)"
    elif next_field == "contact phone number":
        return f"{ack} Could you share a contact phone number for the SMS confirmation?"
    else:
        return f"{ack} Could you provide more details?"


def _do_booking(session: ChatSession, dt: datetime) -> str:
    """Execute the booking: send SMS + record in calendar."""
    ext = session.extracted
    phone = ext.contact_phone or ""
    sms_body = (
        f"Appointment confirmed for {ext.patient_name or 'you'} "
        f"with {ext.department or 'General Medicine'} "
        f"on {dt.strftime('%Y-%m-%d at %H:%M')}. "
        f"Reply YES to confirm or call to reschedule."
    )
    message_sid = sms_service.send_confirmation(phone, sms_body)

    calendar_service.book_slot(
        dt=dt,
        patient_name=ext.patient_name or "Unknown",
        department=ext.department or "General",
        contact_phone=phone,
        sms_sid=message_sid,
    )

    session.scheduled_datetime = dt
    session.confirmation_message_sid = message_sid
    session.state = ConversationState.completed

    return (
        f"✅ Appointment confirmed for {ext.patient_name} with "
        f"{ext.department} on {dt.strftime('%A, %B %d at %H:%M')}. "
        f"An SMS confirmation has been sent to {phone} "
        f"(SID: {message_sid}). Is there anything else I can help you with?"
    )


def _resolve_same_day(session: ChatSession, existing_bookings: list[dict]) -> Optional[datetime]:
    """
    Resolve "same day <time>" / "that day at X" during a reschedule conversation.

    "Same day" refers to the date of the existing appointment being rescheduled,
    NOT today. Returns the resolved datetime, or None if the message doesn't
    look like a same-day request or no booking context is available.
    """
    lower = (session.messages[-1].get("content", "") if session.messages else "").lower()

    same_day_triggers = ("same day", "that day", "the same day", "same date", "that date")
    if not any(t in lower for t in same_day_triggers):
        return None

    hour = _extract_time_only(lower)
    if hour is None:
        return None

    # Anchor date = the appointment being rescheduled (first booking of the patient)
    if not existing_bookings:
        return None
    anchor_dt = datetime.fromisoformat(existing_bookings[0]["datetime"])

    resolved = anchor_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    logger.info(
        f"Reschedule: resolved '{lower}' as same-day ({anchor_dt.date()}) at {hour:02d}:00 "
        f"→ {resolved}"
    )
    return resolved


def _confirm_or_execute_reschedule(
    session: ChatSession, booking: dict, old_dt: datetime, new_dt: datetime, lower_msg: str
):
    """Check new slot availability, then confirm or suggest alternatives."""
    # If the user's message is a confirmation, execute immediately
    if any(w in lower_msg for w in ["yes", "confirm", "go ahead", "sure", "do it", "ok", "okay", "sounds good", "please"]):
        reply = _do_reschedule(session, booking["id"], old_dt, new_dt)
        session.messages.append({"role": "assistant", "content": reply})
        return ChatResponse(
            reply=reply,
            session_id=session.session_id,
            state=session.state,
            extracted=session.extracted,
            scheduled_datetime=session.scheduled_datetime,
            confirmation_message_sid=session.confirmation_message_sid,
        )

    # Check availability of the new slot
    if calendar_service.check_availability(new_dt):
        session.state = ConversationState.confirming
        session.pending_slot = new_dt
        session.reschedule_booking_id = booking["id"]
        session.reschedule_old_dt = old_dt
        reply = (
            f"I found your appointment on "
            f"{old_dt.strftime('%A, %B %d at %H:%M')} "
            f"with {booking['department']}. "
            f"The new slot on {new_dt.strftime('%A, %B %d at %H:%M')} "
            f"is available. Shall I reschedule to this time? "
            f"Just say 'yes' to confirm."
        )
    else:
        session.state = ConversationState.suggesting_alternatives
        alternatives = _find_alternative_slots(new_dt, count=3)
        session.suggested_slots = [dt.isoformat() for dt in alternatives]
        session.pending_slot = alternatives[0] if alternatives else None
        session.reschedule_booking_id = booking["id"]
        session.reschedule_old_dt = old_dt
        reply = (
            f"I found your appointment on "
            f"{old_dt.strftime('%A, %B %d at %H:%M')} with "
            f"{booking['department']}. The requested new time "
            f"({new_dt.strftime('%A, %B %d at %H:%M')}) is not available. "
            f"Here are the next available slots:\n"
            + _format_slot_list(alternatives) +
            "\n\nWould any of these work? Just say the number."
        )

    session.messages.append({"role": "assistant", "content": reply})
    return ChatResponse(
        reply=reply,
        session_id=session.session_id,
        state=session.state,
        extracted=session.extracted,
        suggested_slots=session.suggested_slots,
    )


def _do_reschedule(session: ChatSession, booking_id: int, old_dt: datetime, new_dt: datetime) -> str:
    """Execute a reschedule: update the existing booking's datetime + send SMS."""
    ext = session.extracted
    # Look up the existing booking to get phone and department
    existing_bookings = calendar_service.find_bookings_by_name(ext.patient_name)
    booking = next((b for b in existing_bookings if b["id"] == booking_id), None)

    phone = booking["contact_phone"] if booking and booking.get("contact_phone") else ""
    department = booking["department"] if booking and booking.get("department") else ext.department or "General"

    # Update the booking datetime in the DB
    calendar_service.reschedule_booking(booking_id, new_dt)

    # Send SMS about the reschedule
    sms_body = (
        f"Appointment rescheduled for {ext.patient_name or 'you'} "
        f"with {department} "
        f"from {old_dt.strftime('%Y-%m-%d at %H:%M')} "
        f"to {new_dt.strftime('%Y-%m-%d at %H:%M')}. "
        f"Reply YES to confirm or call to cancel."
    )
    message_sid = sms_service.send_confirmation(phone, sms_body)

    session.scheduled_datetime = new_dt
    session.confirmation_message_sid = message_sid
    session.state = ConversationState.completed

    return (
        f"✅ Appointment rescheduled for {ext.patient_name} from "
        f"{old_dt.strftime('%A, %B %d at %H:%M')} to "
        f"{new_dt.strftime('%A, %B %d at %H:%M')}. "
        f"An SMS confirmation has been sent to {phone} "
        f"(SID: {message_sid}). Is there anything else I can help you with?"
    )


def _deterministic_reschedule_reply(ext: ExtractedAppointment, session: "ChatSession") -> str:
    """Generate a deterministic reply for reschedule — only asks for name + new datetime."""
    missing = _missing_fields_for_reschedule(ext)

    if not missing:
        return "Let me look up your appointment and check the new time."

    ack_parts = []
    if ext.patient_name:
        ack_parts.append(f"Great, {ext.patient_name}!")
    ack = " ".join(ack_parts) if ack_parts else "Got it."

    next_field = missing[0]
    if next_field == "patient name":
        return f"{ack} To reschedule, I'll need your full name to look up your appointment. What's your name?"
    elif next_field == "new preferred date and time":
        return f"{ack} What new date and time would you like? (Business hours are 09:00–17:00, weekdays only.)"
    else:
        return f"{ack} Could you provide more details?"


def _do_cancel(session: ChatSession, booking: dict) -> str:
    """Execute a cancellation: delete the booking + send SMS notification."""
    ext = session.extracted
    phone = booking.get("contact_phone") or ""
    name = ext.patient_name or booking.get("patient_name") or "you"

    # Delete the booking from the DB
    calendar_service.cancel_booking(booking["id"])

    # Send SMS about the cancellation (best-effort)
    sms_body = (
        f"Appointment cancelled for {name} "
        f"with {booking.get('department', 'General')} "
        f"on {booking['datetime'][:16].replace('T', ' ')}. "
        f"Reply YES to rebook or call to reschedule."
    )
    message_sid = sms_service.send_confirmation(phone, sms_body)

    session.state = ConversationState.cancelled
    session.reschedule_booking_id = None
    session.reschedule_old_dt = None

    return (
        f"✅ Your appointment on "
        f"{booking['datetime'][:16].replace('T', ' ')} with "
        f"{booking.get('department', 'General')} has been cancelled. "
        f"A confirmation SMS has been sent. "
        f"Is there anything else I can help you with?"
    )


def _deterministic_cancel_reply(ext: ExtractedAppointment, session: "ChatSession") -> str:
    """Generate a deterministic reply for cancel — only asks for patient name."""
    if not ext.patient_name:
        return "To cancel an appointment, I'll need your full name to look up your booking. What's your name?"
    return "Let me look up your appointments."


def _format_booking_list(bookings: list[dict]) -> str:
    """Format a list of bookings as a numbered list for the chat UI."""
    lines = []
    for i, b in enumerate(bookings):
        b_dt = datetime.fromisoformat(b["datetime"])
        lines.append(f"  {i + 1}. {b_dt.strftime('%A, %B %d at %H:%M')} — {b['department']}")
    return "\n".join(lines)


def _format_slot_list(slots: list[datetime]) -> str:
    """Format a list of alternative slot datetimes as a numbered list."""
    lines = []
    for i, dt in enumerate(slots):
        lines.append(f"  {i + 1}. {dt.strftime('%A, %B %d at %H:%M')}")
    return "\n".join(lines)


def _handle_cancel_intent(session: ChatSession, lower_msg: str):
    """
    Handle the cancel intent flow: ask for name → list bookings → confirm → delete.

    Returns a ChatResponse if handled, or None to fall through to the normal flow.
    """
    ext = session.extracted

    # Not enough info yet — ask for the name
    if not ext.patient_name:
        reply = _deterministic_cancel_reply(ext, session)
        session.state = ConversationState.collecting_info
        session.messages.append({"role": "assistant", "content": reply})
        return ChatResponse(
            reply=reply,
            session_id=session.session_id,
            state=session.state,
            extracted=session.extracted,
        )

    # Look up existing bookings for this patient
    existing_bookings = calendar_service.find_bookings_by_name(ext.patient_name)

    if not existing_bookings:
        reply = (
            f"I couldn't find any appointments for {ext.patient_name}. "
            f"Would you like to book a new appointment instead?"
        )
        session.state = ConversationState.completed
        session.messages.append({"role": "assistant", "content": reply})
        return ChatResponse(
            reply=reply,
            session_id=session.session_id,
            state=session.state,
            extracted=session.extracted,
        )

    # If user is picking a booking number (1, 2, 3...) after we listed them
    pick_match = re.fullmatch(r'\s*([1-9]\d?)\s*', lower_msg)
    if pick_match and len(session.messages) >= 2:
        # Check if the last bot message listed bookings
        last_bot = next((m["content"] for m in reversed(session.messages) if m.get("role") == "assistant"), "")
        if "Which one would you like to cancel" in last_bot:
            idx = int(pick_match.group(1)) - 1
            if 0 <= idx < len(existing_bookings):
                return _confirm_or_execute_cancel(session, existing_bookings[idx], lower_msg)

    # If user is answering with a TIME instead of a number (e.g. "monday 3pm",
    # "3pm", "the 15:00 one") while we're listing bookings — match by time
    time_match = _extract_time_only(lower_msg)
    if time_match is not None and len(session.messages) >= 2:
        last_bot = next((m["content"] for m in reversed(session.messages) if m.get("role") == "assistant"), "")
        if "Which one would you like to cancel" in last_bot:
            # Match booking(s) whose hour equals the mentioned time
            candidates = [
                b for b in existing_bookings
                if datetime.fromisoformat(b["datetime"]).hour == time_match
            ]
            if len(candidates) == 1:
                return _confirm_or_execute_cancel(session, candidates[0], lower_msg)
            elif len(candidates) > 1:
                # Same hour on different days — disambiguate by weekday if mentioned
                weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                mentioned_wd = [i for i, wd in enumerate(weekdays) if re.search(rf'\b{wd}\b', lower_msg)]
                if len(mentioned_wd) == 1:
                    candidates = [
                        b for b in candidates
                        if datetime.fromisoformat(b["datetime"]).weekday() == mentioned_wd[0]
                    ]
                    if len(candidates) == 1:
                        return _confirm_or_execute_cancel(session, candidates[0], lower_msg)
                # Still ambiguous — re-list the matching ones
                reply = (
                    f"There are {len(candidates)} appointments at that time:\n"
                    + _format_booking_list(candidates) +
                    "\n\nWhich one? Just say the number."
                )
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                )
            else:
                reply = (
                    f"I don't see an appointment at {time_match:02d}:00. "
                    f"Here are your appointments:\n"
                    + _format_booking_list(existing_bookings) +
                    "\n\nWhich one would you like to cancel? Just say the number."
                )
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                )

    # Check for confirmation keywords if we're confirming a specific cancel
    if session.pending_slot is None and session.reschedule_booking_id:
        if any(w in lower_msg for w in ["yes", "confirm", "cancel it", "go ahead", "sure", "ok", "okay", "please"]):
            booking = next(
                (b for b in existing_bookings if b["id"] == session.reschedule_booking_id),
                None,
            )
            if booking:
                return _execute_cancel(session, booking)
        elif any(w in lower_msg for w in ["no", "different", "another", "not", "keep"]):
            session.reschedule_booking_id = None
            reply = "No problem, I'll keep the appointment. Is there anything else I can help you with?"
            session.state = ConversationState.completed
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )

    # Single booking — confirm cancellation directly
    if len(existing_bookings) == 1:
        return _confirm_or_execute_cancel(session, existing_bookings[0], lower_msg)

    # Multiple bookings — ask which one
    reply = (
        f"I found {len(existing_bookings)} appointments for {ext.patient_name}:\n"
        + _format_booking_list(existing_bookings) +
        "\n\nWhich one would you like to cancel? Just say the number, "
        "or tell me the time (e.g. '3pm')."
    )
    session.state = ConversationState.collecting_info
    session.messages.append({"role": "assistant", "content": reply})
    return ChatResponse(
        reply=reply,
        session_id=session.session_id,
        state=session.state,
        extracted=session.extracted,
    )


def _confirm_or_execute_cancel(session: ChatSession, booking: dict, lower_msg: str):
    """Confirm cancellation for a single booking, or execute if user confirms."""
    # If the user's message is a confirmation, execute immediately
    if any(w in lower_msg for w in ["yes", "confirm", "cancel it", "go ahead", "sure", "ok", "okay", "please"]):
        return _execute_cancel(session, booking)

    # Otherwise, ask for confirmation
    b_dt = datetime.fromisoformat(booking["datetime"])
    reply = (
        f"I found your appointment on "
        f"{b_dt.strftime('%A, %B %d at %H:%M')} with "
        f"{booking.get('department', 'General')}. "
        f"Shall I cancel it? Just say 'yes' to confirm."
    )
    session.state = ConversationState.confirming
    session.reschedule_booking_id = booking["id"]  # Reuse field to track pending cancel
    session.messages.append({"role": "assistant", "content": reply})
    return ChatResponse(
        reply=reply,
        session_id=session.session_id,
        state=session.state,
        extracted=session.extracted,
    )


def _execute_cancel(session: ChatSession, booking: dict):
    """Delete the booking and return the completion response."""
    reply = _do_cancel(session, booking)
    session.messages.append({"role": "assistant", "content": reply})
    return ChatResponse(
        reply=reply,
        session_id=session.session_id,
        state=session.state,
        extracted=session.extracted,
    )


def process_chat_request(request: ChatRequest) -> ChatResponse:
    """
    Process a single turn in the conversational booking flow.

    This is the main entry point for the chat endpoint. It:
    1. Retrieves/creates the session
    2. Extracts any new info from the user's message
    3. Determines the conversation state transition
    4. Generates a reply (possibly with calendar actions)
    """
    session = _get_or_create_session(request.session_id)
    user_msg = request.message.strip()

    # Store user message in history
    session.messages.append({"role": "user", "content": user_msg})

    # ── Handle cancellation intent early ──────────────────────────────────────
    lower_msg = user_msg.lower()
    # "cancel my appointment" etc. is a GENUINE cancel request — let extraction
    # and the cancel flow handle it. Only short abort phrases (never mind, stop)
    # or plain "cancel" mid-booking should abort the current conversation.
    mentions_appointment = any(w in lower_msg for w in ["appointment", "booking", "reschedule", "book"])
    if any(w in lower_msg for w in ["cancel", "never mind", "stop", "abort", "quit"]):
        is_plain_abort = (
            len(user_msg.split()) <= 3 and not mentions_appointment
        ) or "never mind" in lower_msg or "abort" in lower_msg or "quit" in lower_msg
        if is_plain_abort and (session.state != ConversationState.greeting or len(session.messages) > 2):
            session.state = ConversationState.cancelled
            reply = (
                "No problem! Your request has been cancelled. "
                "If you'd like to book an appointment later, just let me know. 👋"
            )
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )

    # ── Handle completed state — booking is done, user may want another ───────
    if session.state == ConversationState.completed:
        # Reset extracted info so the new message is treated freshly
        session.extracted = ExtractedAppointment(intent=AppointmentIntent.inquiry)
        session.scheduled_datetime = None
        session.confirmation_message_sid = None
        session.suggested_slots = []
        session.pending_slot = None
        session.reschedule_booking_id = None
        session.reschedule_old_dt = None
        # Fall through to extraction below — the new intent will be routed
        # (schedule → booking flow, cancel → cancel flow, etc.)
        pass

    # ── Step 1: Extract info from user's message ──────────────────────────────
    # Skip extraction if user is just picking a slot number or confirming —
    # otherwise the LLM re-extracts the original datetime and we loop.
    skip_extraction = (
        session.state in (ConversationState.suggesting_alternatives, ConversationState.confirming)
        and (
            # User is saying a number (1, 2, 3) or a short confirmation
            lower_msg.strip() in ("1", "2", "3", "yes", "ok", "okay", "sure", "no")
            or any(w in lower_msg for w in ["first", "second", "third", "1st", "2nd", "3rd", "yes", "sure", "ok", "confirm", "book it", "go ahead", "sounds good", "that works"])
        )
    )

    if not skip_extraction:
        session.extracted = _extract_from_chat(user_msg, session.extracted)

    # ── Step 1b: If department is still missing and user is confirming a suggestion ─
    if not session.extracted.department and session.state == ConversationState.collecting_info:
        # Check if the last bot message suggested a department
        last_bot_msg = ""
        for m in reversed(session.messages):
            if m.get("role") == "assistant":
                last_bot_msg = m.get("content", "")
                break

        if "suggest the" in last_bot_msg.lower() and "department" in last_bot_msg.lower():
            # Bot suggested a department — check if user is confirming
            if any(w in lower_msg for w in ["yes", "right", "correct", "sure", "ok", "okay", "sounds", "good", "that", "please"]):
                # Extract the department name from the bot's message
                import re as _re
                match = _re.search(r'\*\*(.+?)\*\*', last_bot_msg)
                if match:
                    session.extracted.department = match.group(1).replace(" Department", "").strip()
                    logger.info(f"User confirmed suggested department: {session.extracted.department}")
            elif any(w in lower_msg for w in ["no", "different", "other", "not"]):
                # User wants a different department — let the deterministic reply ask again
                pass

    logger.info(
        f"Chat session={session.session_id}: extracted update → "
        f"intent={session.extracted.intent.value}, "
        f"name={session.extracted.patient_name}, "
        f"dept={session.extracted.department}, "
        f"dt={session.extracted.preferred_datetime}, "
        f"phone={session.extracted.contact_phone}"
    )

    # ── Step 1c: Off-topic guard — redirect if user asks unrelated questions ──
    if session.state == ConversationState.collecting_info:
        # Check if the extraction added ANY new info from this message
        # by comparing before/after. We do this by checking if the user's
        # message looks like an off-topic question.
        if _is_off_topic(user_msg, session.extracted):
            missing = _missing_fields(session.extracted)
            next_field = missing[0] if missing else "your request"
            reply = (
                f"I'm a hospital appointment scheduling bot — I can help you book, "
                f"reschedule, or cancel medical appointments. I'm not able to answer "
                f"other questions.\n\n"
                f"To continue booking your appointment, could you please provide "
                f"your {next_field}?"
            )
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )

    # ── Step 1d: Handle "which booking to reschedule" selection ───────────────
    # User can answer with a number ("2") OR a time ("3pm") to pick a booking
    if (session.extracted.intent == AppointmentIntent.reschedule
            and session.state == ConversationState.collecting_info
            and session.extracted.patient_name):
        existing_bookings = calendar_service.find_bookings_by_name(session.extracted.patient_name)
        picked_booking = None

        if (lower_msg.strip() in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")
                and session.extracted.preferred_datetime
                and len(existing_bookings) > 1):
            # Number pick — check the last bot message listed bookings
            last_bot = next((m["content"] for m in reversed(session.messages) if m.get("role") == "assistant"), "")
            if "Which one would you like to reschedule" in last_bot:
                pick_idx = int(lower_msg.strip()) - 1
                if 0 <= pick_idx < len(existing_bookings):
                    picked_booking = existing_bookings[pick_idx]
        elif len(existing_bookings) > 1:
            # Time pick (e.g. "3pm") — check the last bot message listed bookings
            last_bot = next((m["content"] for m in reversed(session.messages) if m.get("role") == "assistant"), "")
            if "Which one would you like to reschedule" in last_bot:
                time_match = _extract_time_only(lower_msg)
                if time_match is not None:
                    candidates = [
                        b for b in existing_bookings
                        if datetime.fromisoformat(b["datetime"]).hour == time_match
                    ]
                    if len(candidates) == 1:
                        picked_booking = candidates[0]
                        # The mentioned time is the booking to KEEP — the new
                        # preferred datetime still needs to be asked
                        session.extracted.preferred_datetime = None

        if picked_booking is not None:
            booking = picked_booking
            old_dt = datetime.fromisoformat(booking["datetime"])
            # Handle "same day <time>" anchored to the selected booking's date
            same_day_dt = _resolve_same_day(session, [booking])
            new_dt = same_day_dt if same_day_dt is not None else session.extracted.preferred_datetime

            # If no new datetime yet (time-pick consumed the message), ask for it
            if new_dt is None:
                session.state = ConversationState.collecting_info
                session.reschedule_booking_id = booking["id"]
                session.reschedule_old_dt = old_dt
                reply = (
                    f"Got it — rescheduling the appointment on "
                    f"{old_dt.strftime('%A, %B %d at %H:%M')} with "
                    f"{booking['department']}. "
                    f"What new date and time would you like?"
                )
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                )

            if calendar_service.check_availability(new_dt):
                session.state = ConversationState.confirming
                session.pending_slot = new_dt
                session.reschedule_booking_id = booking["id"]
                session.reschedule_old_dt = old_dt
                reply = (
                    f"I found your appointment on "
                    f"{old_dt.strftime('%A, %B %d at %H:%M')} "
                    f"with {booking['department']}. "
                    f"The new slot on {new_dt.strftime('%A, %B %d at %H:%M')} "
                    f"is available. Shall I reschedule to this time? "
                    f"Just say 'yes' to confirm."
                )
            else:
                session.state = ConversationState.suggesting_alternatives
                alternatives = _find_alternative_slots(new_dt, count=3)
                session.suggested_slots = [dt.isoformat() for dt in alternatives]
                session.pending_slot = alternatives[0] if alternatives else None
                session.reschedule_booking_id = booking["id"]
                session.reschedule_old_dt = old_dt
                slot_descriptions = []
                for i, alt in enumerate(alternatives):
                    slot_descriptions.append(f"  {i + 1}. {alt.strftime('%A, %B %d at %H:%M')}")
                reply = (
                    f"The requested new time is not available. "
                    f"Here are the next available slots:\n"
                    + "\n".join(slot_descriptions) +
                    f"\n\nWould any of these work? Just say the number."
                )
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
                suggested_slots=session.suggested_slots,
            )

    # ── Step 2: Handle cancel intent ──────────────────────────────────────────
    if session.extracted.intent == AppointmentIntent.cancel:
        return _handle_cancel_intent(session, lower_msg)

    # ── Step 2b: Handle reschedule intent ─────────────────────────────────────
    if (session.extracted.intent == AppointmentIntent.reschedule
            and session.state not in (ConversationState.confirming, ConversationState.suggesting_alternatives)):
        # For reschedule, we only need: patient name + new datetime
        # Phone and department come from the existing booking

        # A booking already selected earlier (via time/number pick)? Use it directly.
        if session.reschedule_booking_id and session.reschedule_old_dt:
            selected = next(
                (b for b in calendar_service.find_bookings_by_name(session.extracted.patient_name)
                 if b["id"] == session.reschedule_booking_id),
                None,
            )
            if selected and session.extracted.preferred_datetime:
                # We have booking + new datetime — go reschedule it
                old_dt = session.reschedule_old_dt
                new_dt = session.extracted.preferred_datetime
                # (fall through to the single-booking block below via booking var)
                booking = selected
                return _confirm_or_execute_reschedule(session, booking, old_dt, new_dt, lower_msg)
            elif selected and not session.extracted.preferred_datetime:
                # Booking selected, waiting for the new time
                session.state = ConversationState.collecting_info
                reply = (
                    f"Got it — rescheduling the appointment on "
                    f"{datetime.fromisoformat(selected['datetime']).strftime('%A, %B %d at %H:%M')} "
                    f"with {selected['department']}. "
                    f"What new date and time would you like?"
                )
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                )

        # Multiple bookings and none picked yet? List them FIRST — before asking
        # for the new time or anything else. This works even when the user has
        # given name + time together (e.g. "monday 3pm" = WHICH booking, not new time).
        if session.extracted.patient_name and not session.reschedule_booking_id:
            early_bookings = calendar_service.find_bookings_by_name(session.extracted.patient_name)
            if len(early_bookings) > 1:
                reply = (
                    f"I found {len(early_bookings)} appointments for "
                    f"{session.extracted.patient_name}:\n"
                    + _format_booking_list(early_bookings) +
                    "\n\nWhich one would you like to reschedule? Just say the number, "
                    "or tell me the time (e.g. '3pm')."
                )
                session.state = ConversationState.collecting_info
                # Clear any datetime the LLM guessed from the pick answer —
                # it referred to WHICH booking, not the new time
                session.extracted.preferred_datetime = None
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                )

        if not _is_reschedule_info_complete(session.extracted):
            session.state = ConversationState.collecting_info
            reply = _deterministic_reschedule_reply(session.extracted, session)
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )

        # We have name + new datetime — look up existing bookings
        existing_bookings = calendar_service.find_bookings_by_name(session.extracted.patient_name)

        if not existing_bookings:
            reply = (
                f"I couldn't find any existing appointments for "
                f"{session.extracted.patient_name}. Would you like to book a "
                f"new appointment instead?"
            )
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )

        # Handle "same day <time>" / "that day at X" — anchor to the existing
        # appointment's date instead of whatever the LLM guessed (often today).
        same_day_dt = _resolve_same_day(session, existing_bookings)
        if same_day_dt is not None:
            session.extracted.preferred_datetime = same_day_dt

        if len(existing_bookings) == 1:
            # Single booking — proceed with reschedule
            # If a booking was already selected earlier (time/number pick), use it
            if session.reschedule_booking_id:
                booking = next(
                    (b for b in existing_bookings if b["id"] == session.reschedule_booking_id),
                    existing_bookings[0],
                )
            else:
                booking = existing_bookings[0]
            old_dt = datetime.fromisoformat(booking["datetime"])
            new_dt = session.extracted.preferred_datetime

            # Check availability of the new slot
            if calendar_service.check_availability(new_dt):
                # Available — ask for confirmation or reschedule directly
                session.state = ConversationState.confirming
                session.pending_slot = new_dt
                session.reschedule_booking_id = booking["id"]
                session.reschedule_old_dt = old_dt

                if any(w in lower_msg for w in ["yes", "confirm", "go ahead", "sure", "do it", "ok", "okay", "sounds good", "please"]):
                    reply = _do_reschedule(session, booking["id"], old_dt, new_dt)
                else:
                    reply = (
                        f"I found your appointment on "
                        f"{old_dt.strftime('%A, %B %d at %H:%M')} "
                        f"with {booking['department']}. "
                        f"The new slot on {new_dt.strftime('%A, %B %d at %H:%M')} "
                        f"is available. Shall I reschedule to this time? "
                        f"Just say 'yes' to confirm."
                    )

                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                    scheduled_datetime=session.scheduled_datetime,
                    confirmation_message_sid=session.confirmation_message_sid,
                )
            else:
                # New slot unavailable — find alternatives
                session.state = ConversationState.suggesting_alternatives
                alternatives = _find_alternative_slots(new_dt, count=3)

                if not alternatives:
                    session.state = ConversationState.collecting_info
                    reply = (
                        f"Unfortunately, the slot on "
                        f"{new_dt.strftime('%A, %B %d at %H:%M')} "
                        f"is not available, and I couldn't find any open slots "
                        f"within the next 7 days. Could you suggest a different "
                        f"date or time?"
                    )
                else:
                    session.suggested_slots = [dt.isoformat() for dt in alternatives]
                    session.pending_slot = alternatives[0]
                    session.reschedule_booking_id = booking["id"]
                    session.reschedule_old_dt = old_dt

                    slot_descriptions = []
                    for i, alt in enumerate(alternatives):
                        slot_descriptions.append(
                            f"  {i + 1}. {alt.strftime('%A, %B %d at %H:%M')}"
                        )

                    reply = (
                        f"I found your appointment on "
                        f"{old_dt.strftime('%A, %B %d at %H:%M')} "
                        f"with {booking['department']}. "
                        f"Unfortunately, the requested new time "
                        f"({new_dt.strftime('%A, %B %d at %H:%M')}) is not available. "
                        f"Here are the next available slots:\n"
                        + "\n".join(slot_descriptions) +
                        f"\n\nWould any of these work? Just say the number (1, 2, or 3) "
                        f"or tell me a different preferred time."
                    )

                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                    suggested_slots=session.suggested_slots,
                )
        else:
            # Multiple bookings — ask which one to reschedule
            reply = (
                f"I found {len(existing_bookings)} appointments for "
                f"{session.extracted.patient_name}:\n"
                + _format_booking_list(existing_bookings) +
                f"\n\nWhich one would you like to reschedule? Just say the number, "
                f"or tell me the time (e.g. '3pm')."
            )
            session.state = ConversationState.collecting_info
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )

    # ── Step 3: Handle inquiry intent ─────────────────────────────────────────
    if session.extracted.intent == AppointmentIntent.inquiry and not _is_info_complete(session.extracted):
        session.state = ConversationState.collecting_info
        # Use deterministic reply — LLM improvisation causes confusion
        reply = _deterministic_collecting_reply(session.extracted, session)
        session.messages.append({"role": "assistant", "content": reply})
        return ChatResponse(
            reply=reply,
            session_id=session.session_id,
            state=session.state,
            extracted=session.extracted,
        )

    # ── Step 4: Check if we have enough info to check availability ────────────
    # For reschedule, we only need name + datetime (phone/department come from existing booking)
    if session.extracted.intent == AppointmentIntent.reschedule:
        if not _is_reschedule_info_complete(session.extracted):
            session.state = ConversationState.collecting_info
            reply = _deterministic_reschedule_reply(session.extracted, session)
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )
    elif not _is_info_complete(session.extracted):
        session.state = ConversationState.collecting_info
        # Use deterministic reply — asks for exactly the next missing field
        reply = _deterministic_collecting_reply(session.extracted, session)
        session.messages.append({"role": "assistant", "content": reply})
        return ChatResponse(
            reply=reply,
            session_id=session.session_id,
            state=session.state,
            extracted=session.extracted,
        )

    # ── Step 5: We have all info — check availability ─────────────────────────
    requested_dt = session.extracted.preferred_datetime

    # If we're in suggesting_alternatives and user is responding to a suggestion
    if session.state == ConversationState.suggesting_alternatives and session.pending_slot:
        # Check if user is agreeing or picking a suggested slot
        # Match "1", "first", "1st", "one", "yes", etc.
        msg_clean = lower_msg.strip()
        picks_first = msg_clean in ("1", "first", "1st", "one") or any(w in lower_msg for w in ["yes", "sure", "ok", "okay", "sounds good", "that works", "confirm", "book it", "go ahead", "first", "1st"])
        picks_second = msg_clean in ("2", "second", "2nd", "two") or any(w in lower_msg for w in ["second", "2nd", "next one"])
        picks_third = msg_clean in ("3", "third", "3rd", "three") or any(w in lower_msg for w in ["third", "3rd", "last one"])

        if picks_first:
            # Book the pending slot (first suggestion) — or reschedule if applicable
            if session.reschedule_booking_id and session.reschedule_old_dt:
                reply = _do_reschedule(session, session.reschedule_booking_id, session.reschedule_old_dt, session.pending_slot)
            else:
                reply = _do_booking(session, session.pending_slot)
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
                scheduled_datetime=session.scheduled_datetime,
                confirmation_message_sid=session.confirmation_message_sid,
            )
        elif picks_second:
            if len(session.suggested_slots) >= 2:
                second_dt = datetime.fromisoformat(session.suggested_slots[1])
                if session.reschedule_booking_id and session.reschedule_old_dt:
                    reply = _do_reschedule(session, session.reschedule_booking_id, session.reschedule_old_dt, second_dt)
                else:
                    reply = _do_booking(session, second_dt)
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                    scheduled_datetime=session.scheduled_datetime,
                    confirmation_message_sid=session.confirmation_message_sid,
                )
        elif picks_third:
            if len(session.suggested_slots) >= 3:
                third_dt = datetime.fromisoformat(session.suggested_slots[2])
                if session.reschedule_booking_id and session.reschedule_old_dt:
                    reply = _do_reschedule(session, session.reschedule_booking_id, session.reschedule_old_dt, third_dt)
                else:
                    reply = _do_booking(session, third_dt)
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                    scheduled_datetime=session.scheduled_datetime,
                    confirmation_message_sid=session.confirmation_message_sid,
                )
        else:
            # User said something else — could be a new date/time or additional info
            # First, try local date parsing on the raw user message — this catches
            # vague expressions like "any day after 15" that the LLM misses
            local_dt = _extract_datetime_from_text(user_msg)

            # "samday"/"same day" (with possible typo) while suggestions are on
            # screen = "keep the date of the suggested slot I'm replying to".
            # Anchor to the FIRST suggested slot's date (usually what the user means).
            lower_now = user_msg.lower()
            same_day_triggers = ("samday", "same day", "same date", "that day", "that date")
            if local_dt is None and any(t in lower_now for t in same_day_triggers):
                if session.suggested_slots:
                    anchor = datetime.fromisoformat(session.suggested_slots[0])
                    hour = _extract_time_only(lower_now)
                    if hour is not None:
                        local_dt = anchor.replace(hour=hour, minute=0, second=0, microsecond=0)
                        logger.info(
                            f"Suggesting alternatives: resolved '{lower_now}' as same-day "
                            f"({anchor.date()}) at {hour:02d}:00 → {local_dt}"
                        )
            if local_dt:
                session.extracted.preferred_datetime = local_dt
                new_dt = local_dt
            else:
                # Check if the user is specifying just an hour preference (e.g., "15 time of any day")
                hour_pref = _extract_hour_preference(user_msg)
                if hour_pref is not None and 9 <= hour_pref <= 16:
                    # Find the next available slot at this hour, starting from tomorrow
                    now = datetime.now()
                    candidate = now.replace(hour=hour_pref, minute=0, second=0, microsecond=0)
                    if candidate <= now:
                        candidate += timedelta(days=1)
                    # Search up to 7 days for a slot at this hour
                    for _ in range(7):
                        if calendar_service.check_availability(candidate):
                            session.extracted.preferred_datetime = candidate
                            new_dt = candidate
                            break
                        candidate += timedelta(days=1)
                    else:
                        # No slot at that hour found — tell the user
                        reply = (
                            f"Sorry, I couldn't find an available slot at {hour_pref:02d}:00 "
                            f"within the next 7 days. Could you try a different time?"
                        )
                        session.messages.append({"role": "assistant", "content": reply})
                        return ChatResponse(
                            reply=reply,
                            session_id=session.session_id,
                            state=session.state,
                            extracted=session.extracted,
                            suggested_slots=session.suggested_slots,
                        )
                else:
                    new_dt = session.extracted.preferred_datetime

            if new_dt:
                for slot_iso in session.suggested_slots:
                    slot_dt = datetime.fromisoformat(slot_iso)
                    # Compare date and hour (ignore minutes since slots are hourly)
                    if new_dt.date() == slot_dt.date() and new_dt.hour == slot_dt.hour:
                        if session.reschedule_booking_id and session.reschedule_old_dt:
                            reply = _do_reschedule(session, session.reschedule_booking_id, session.reschedule_old_dt, slot_dt)
                        else:
                            reply = _do_booking(session, slot_dt)
                        session.messages.append({"role": "assistant", "content": reply})
                        return ChatResponse(
                            reply=reply,
                            session_id=session.session_id,
                            state=session.state,
                            extracted=session.extracted,
                            scheduled_datetime=session.scheduled_datetime,
                            confirmation_message_sid=session.confirmation_message_sid,
                        )
                # The user provided a new datetime that doesn't match suggestions
                # — treat it as a new preferred time and re-check availability
                session.pending_slot = None
                session.suggested_slots = []
                requested_dt = new_dt
            else:
                # User didn't provide a new datetime — check if they provided
                # other missing info (like phone). If still missing info, ask for it.
                if not _is_info_complete(session.extracted):
                    session.state = ConversationState.collecting_info
                    reply = _deterministic_collecting_reply(session.extracted, session)
                    session.messages.append({"role": "assistant", "content": reply})
                    return ChatResponse(
                        reply=reply,
                        session_id=session.session_id,
                        state=session.state,
                        extracted=session.extracted,
                    )
                # All info present but no new datetime — ask what time they'd like
                session.state = ConversationState.collecting_info
                reply = (
                    "Could you tell me which of the suggested slots works for you? "
                    "Just say 1, 2, or 3, or give me a different date and time."
                )
                session.messages.append({"role": "assistant", "content": reply})
                return ChatResponse(
                    reply=reply,
                    session_id=session.session_id,
                    state=session.state,
                    extracted=session.extracted,
                    suggested_slots=session.suggested_slots,
                )

    # ── Handle confirming state — user was asked to confirm a slot ────────────
    if session.state == ConversationState.confirming and session.pending_slot:
        if any(w in lower_msg for w in ["yes", "book it", "confirm", "go ahead", "sure", "do it", "ok", "okay", "sounds good", "please"]):
            # Check if this is a reschedule confirmation
            if session.reschedule_booking_id and session.reschedule_old_dt:
                reply = _do_reschedule(session, session.reschedule_booking_id, session.reschedule_old_dt, session.pending_slot)
            else:
                reply = _do_booking(session, session.pending_slot)
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
                scheduled_datetime=session.scheduled_datetime,
                confirmation_message_sid=session.confirmation_message_sid,
            )
        elif any(w in lower_msg for w in ["no", "different", "another", "change", "not"]):
            # User wants a different slot — go back to collecting
            session.state = ConversationState.collecting_info
            session.pending_slot = None
            reply = (
                "No problem. What other date or time would work for you? "
                "(Business hours are 09:00–17:00, weekdays only.)"
            )
            session.messages.append({"role": "assistant", "content": reply})
            return ChatResponse(
                reply=reply,
                session_id=session.session_id,
                state=session.state,
                extracted=session.extracted,
            )

    # Check availability of the requested slot
    is_available = calendar_service.check_availability(requested_dt)

    if is_available:
        # Slot is available — ask for confirmation or book directly
        session.state = ConversationState.confirming
        session.pending_slot = requested_dt

        # If user seems to be confirming (e.g., "yes", "book it")
        if any(w in lower_msg for w in ["yes", "book it", "confirm", "go ahead", "sure", "do it"]):
            reply = _do_booking(session, requested_dt)
        else:
            reply = (
                f"Great news! The slot on {requested_dt.strftime('%A, %B %d at %H:%M')} "
                f"is available. Shall I go ahead and book this appointment for you? "
                f"Just say 'yes' to confirm."
            )

        session.messages.append({"role": "assistant", "content": reply})
        return ChatResponse(
            reply=reply,
            session_id=session.session_id,
            state=session.state,
            extracted=session.extracted,
            scheduled_datetime=session.scheduled_datetime,
            confirmation_message_sid=session.confirmation_message_sid,
        )
    else:
        # Slot unavailable — find alternatives
        session.state = ConversationState.suggesting_alternatives
        alternatives = _find_alternative_slots(requested_dt, count=3)

        if not alternatives:
            session.state = ConversationState.collecting_info
            reply = (
                f"Unfortunately, the slot on {requested_dt.strftime('%A, %B %d at %H:%M')} "
                f"is not available, and I couldn't find any open slots within the next 7 days. "
                f"Could you suggest a different date or time?"
            )
        else:
            session.suggested_slots = [dt.isoformat() for dt in alternatives]
            session.pending_slot = alternatives[0]

            slot_descriptions = []
            for i, alt in enumerate(alternatives):
                slot_descriptions.append(
                    f"  {i + 1}. {alt.strftime('%A, %B %d at %H:%M')}"
                )

            reply = (
                f"Unfortunately, the slot on {requested_dt.strftime('%A, %B %d at %H:%M')} "
                f"is not available. Here are the next available slots:\n"
                + "\n".join(slot_descriptions) +
                f"\n\nWould any of these work for you? Just say the number (1, 2, or 3) "
                f"or tell me a different preferred time."
            )

        session.messages.append({"role": "assistant", "content": reply})
        return ChatResponse(
            reply=reply,
            session_id=session.session_id,
            state=session.state,
            extracted=session.extracted,
            suggested_slots=session.suggested_slots,
        )