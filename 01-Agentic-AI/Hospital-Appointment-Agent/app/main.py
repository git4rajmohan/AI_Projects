"""
FastAPI entry point — Appointment Scheduler & Confirmation Bot.

Endpoints:
    POST /api/appointment  — process a scheduling request
    GET  /api/health       — health check
    GET  /                 — basic info
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .schemas import AppointmentRequest, ChatRequest, ChatResponse, ExecutionSummary
from .chain import process_appointment_request, process_chat_request
from .services import calendar_service, sms_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Appointment Scheduler & Confirmation Bot",
    description="LangChain + FastAPI backend that parses natural-language scheduling requests, "
                "checks calendar availability, and sends SMS confirmations.",
    version="1.0.0",
)

# CORS — allow local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (UI)
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web UI."""
    return HTMLResponse(content=(_static_dir / "index.html").read_text(encoding="utf-8"))

@app.get("/api/info")
async def info():
    """Basic service info (JSON)."""
    return {
        "service": "Appointment Scheduler & Confirmation Bot",
        "version": "1.0.0",
        "endpoints": {
            "ui": "GET /",
            "appointment": "POST /api/appointment",
            "health": "GET /api/health",
            "docs": "GET /docs",
        },
    }


@app.get("/api/health")
async def health():
    """Health check — verifies the service is running."""
    return {
        "status": "ok",
        "llm_model": settings.ollama_model,
        "llm_endpoint": settings.openai_api_base,
        "sms_mode": "mock" if settings.is_twilio_mock else "twilio",
    }


@app.post("/api/appointment", response_model=ExecutionSummary)
async def appointment(request: AppointmentRequest) -> ExecutionSummary:
    """
    Process an inbound appointment scheduling request.

    Accepts raw natural-language text and returns a structured execution summary
    with the extracted appointment details, calendar availability, and SMS
    confirmation status.
    """
    logger.info(f"POST /api/appointment — channel={request.channel}")

    try:
        summary = process_appointment_request(request)
        logger.info(f"Result: status={summary.status.value}")
        return summary
    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Conversational chat endpoint — multi-turn appointment booking.

    Maintains session state server-side. The user sends messages naturally,
    and the bot asks clarifying questions, checks availability, suggests
    alternatives, and completes the booking.
    """
    logger.info(f"POST /api/chat — session={request.session_id}, msg={request.message[:80]}...")

    try:
        response = process_chat_request(request)
        logger.info(f"Chat result: state={response.state.value}")
        return response
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/reset")
async def reset_chat(session_id: str = "default"):
    """Reset a chat session, clearing all conversation history."""
    from .chain import _sessions
    if session_id in _sessions:
        del _sessions[session_id]
    return {"status": "ok", "message": f"Session '{session_id}' reset."}


@app.get("/api/calendar/bookings")
async def get_bookings():
    """Return all bookings made through the system."""
    return {"bookings": calendar_service.get_bookings()}


@app.get("/api/calendar/week")
async def get_calendar_week():
    """
    Return a week view of the calendar starting from today.
    Shows each day with hourly slots (09:00–17:00) and their status:
    available, weekend, booked (pre-existing), or booked (new booking).
    """
    from datetime import datetime, timedelta

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = []

    # Get all booked slots (pre-existing + dynamic)
    pre_existing = set(calendar_service.BUSY_SLOTS)
    dynamic_bookings = {b["datetime"] for b in calendar_service.get_bookings()}

    for day_offset in range(7):
        day_dt = today + timedelta(days=day_offset)
        slots = []

        for hour in range(9, 17):  # 09:00 to 16:00
            slot_dt = day_dt.replace(hour=hour)
            slot_key = slot_dt.strftime("%Y-%m-%d %H:%M")
            iso_key = slot_dt.strftime("%Y-%m-%dT%H:00:00")

            if slot_dt.weekday() >= 5:
                status = "weekend"
                booking = None
            elif slot_key in pre_existing:
                status = "booked"
                booking = {"type": "pre-existing", "note": "Already booked"}
            elif iso_key in dynamic_bookings:
                status = "booked"
                # Find the booking details
                booking = next(
                    (b for b in calendar_service.get_bookings() if b["datetime"] == iso_key),
                    None,
                )
            else:
                status = "available"
                booking = None

            slots.append({
                "hour": hour,
                "time": slot_dt.strftime("%H:00"),
                "status": status,
                "booking": booking,
            })

        days.append({
            "date": day_dt.strftime("%Y-%m-%d"),
            "weekday": day_dt.strftime("%A"),
            "is_weekend": day_dt.weekday() >= 5,
            "slots": slots,
        })

    return {"days": days}


@app.get("/api/sms/history")
async def get_sms_history():
    """Return all SMS messages sent through the system."""
    return {"messages": sms_service.get_history()}