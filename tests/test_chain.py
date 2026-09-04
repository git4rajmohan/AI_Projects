"""
Tests for the LangChain extraction chain & orchestrator.

These tests mock the LLM chain (no real LLM calls) for deterministic results.
A separate integration test can be run with the proxy + real Ollama cloud.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.schemas import (
    AppointmentIntent,
    AppointmentRequest,
    ExecutionStatus,
    ExtractedAppointment,
)
from app.chain import process_appointment_request
from app.services import CalendarService


# ── Calendar Service Tests ─────────────────────────────────────────────────────
class TestCalendarService:
    """Unit tests for the calendar service backed by SQLite."""

    def test_weekday_available(self):
        """A weekday during business hours should be available."""
        svc = CalendarService()
        # Wednesday Sep 16, 2026 at 14:00 (not in seed data, not used by other tests)
        dt = datetime(2026, 9, 16, 14, 0)
        assert svc.check_availability(dt) is True

    def test_weekend_unavailable(self):
        """Saturday should be unavailable."""
        svc = CalendarService()
        dt = datetime(2026, 9, 5, 14, 0)  # Saturday
        assert svc.check_availability(dt) is False

    def test_sunday_unavailable(self):
        """Sunday should be unavailable."""
        svc = CalendarService()
        dt = datetime(2026, 9, 6, 11, 0)  # Sunday
        assert svc.check_availability(dt) is False

    def test_outside_business_hours(self):
        """Before 09:00 should be unavailable."""
        svc = CalendarService()
        dt = datetime(2026, 9, 7, 8, 0)  # Monday 8 AM
        assert svc.check_availability(dt) is False

    def test_busy_slot_unavailable(self):
        """A pre-existing booked slot from the DB should be unavailable."""
        svc = CalendarService()
        # Sep 8, 10:00 is in the seed data (Frank Miller - gastroenterology)
        dt = datetime(2026, 9, 8, 10, 0)
        assert svc.check_availability(dt) is False

    def test_find_next_available(self):
        """Should find the next available slot after a busy one."""
        svc = CalendarService()
        dt = datetime(2026, 9, 8, 10, 0)  # Busy (seed data)
        next_slot = svc.find_next_available(dt)
        assert next_slot is not None
        assert svc.check_availability(next_slot) is True


# ── Orchestrator Tests (mocked LLM) ───────────────────────────────────────────
class TestProcessAppointmentRequest:
    """Tests for the full pipeline with mocked LLM chain."""

    def test_schedule_confirmed(self, mock_chain):
        """A schedule request with an available slot should confirm."""
        request = AppointmentRequest(raw_text="Book cardiology for John Doe on 2026-09-07 at 14:00")
        result = process_appointment_request(request)

        assert result.status == ExecutionStatus.confirmed
        assert result.extracted.intent == AppointmentIntent.schedule
        assert result.extracted.patient_name == "John Doe"
        assert result.scheduled_datetime is not None
        assert result.confirmation_message_sid is not None

    def test_cancel_request(self, monkeypatch, mock_extracted_cancel):
        """A cancel request should return cancelled status."""
        from app import chain

        def fake_build_chain():
            mock_runnable = MagicMock()
            mock_runnable.invoke = lambda inputs, config=None, **kw: mock_extracted_cancel
            return mock_runnable, MagicMock()

        monkeypatch.setattr(chain, "_build_chain", fake_build_chain)

        request = AppointmentRequest(raw_text="Cancel appointment for Bob Johnson")
        result = process_appointment_request(request)

        assert result.status == ExecutionStatus.cancelled
        assert result.extracted.intent == AppointmentIntent.cancel
        assert result.scheduled_datetime is None

    def test_no_datetime_extracted(self, monkeypatch):
        """If no datetime is extracted, should return error."""
        from app import chain

        extracted = ExtractedAppointment(
            intent=AppointmentIntent.schedule,
            patient_name="Test Patient",
            preferred_datetime=None,
        )

        def fake_build_chain():
            mock_runnable = MagicMock()
            mock_runnable.invoke = lambda inputs, config=None, **kw: extracted
            return mock_runnable, MagicMock()

        monkeypatch.setattr(chain, "_build_chain", fake_build_chain)

        request = AppointmentRequest(raw_text="I want an appointment")
        result = process_appointment_request(request)

        assert result.status == ExecutionStatus.error
        assert "No preferred datetime" in result.message

    def test_llm_extraction_failure(self, monkeypatch):
        """If the LLM chain raises, should return error gracefully."""
        from app import chain

        def fake_build_chain():
            mock_runnable = MagicMock()
            mock_runnable.invoke = MagicMock(side_effect=Exception("LLM connection failed"))
            return mock_runnable, MagicMock()

        monkeypatch.setattr(chain, "_build_chain", fake_build_chain)

        request = AppointmentRequest(raw_text="Some text")
        result = process_appointment_request(request)

        assert result.status == ExecutionStatus.error
        assert "LLM extraction failed" in result.message

    def test_unavailable_slot_finds_next(self, monkeypatch):
        """When the requested slot is busy, should find the next available."""
        from app import chain

        # Use a busy slot (Sep 8, 10:00 is in BUSY_SLOTS)
        extracted = ExtractedAppointment(
            intent=AppointmentIntent.schedule,
            patient_name="Test Patient",
            department="general",
            preferred_datetime=datetime(2026, 9, 8, 10, 0),
            contact_phone="+15551234567",
        )

        def fake_build_chain():
            mock_runnable = MagicMock()
            mock_runnable.invoke = lambda inputs, config=None, **kw: extracted
            return mock_runnable, MagicMock()

        monkeypatch.setattr(chain, "_build_chain", fake_build_chain)

        request = AppointmentRequest(raw_text="Book on 2026-09-08 at 10:00")
        result = process_appointment_request(request)

        assert result.status == ExecutionStatus.confirmed
        assert result.scheduled_datetime is not None
        # Should NOT be the original busy slot
        assert result.scheduled_datetime != datetime(2026, 9, 8, 10, 0)
        assert "unavailable" in result.message.lower()