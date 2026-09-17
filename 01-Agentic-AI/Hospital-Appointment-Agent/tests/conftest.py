"""
Pytest configuration & shared fixtures.
"""

import os
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

# Load .env before any test imports app modules
load_dotenv()


@pytest.fixture
def sample_schedule_text():
    """A typical scheduling request."""
    return (
        "I need to book a cardiology appointment for John Doe on "
        "2026-09-05 at 14:00. My phone number is +15551234567."
    )


@pytest.fixture
def sample_reschedule_text():
    """A rescheduling request."""
    return (
        "Please reschedule Jane Smith's dermatology appointment from "
        "2026-09-08 to 2026-09-12 at 10:00. Phone: +15559876543."
    )


@pytest.fixture
def sample_cancel_text():
    """A cancellation request."""
    return "Cancel the appointment for Bob Johnson on 2026-09-10."


@pytest.fixture
def sample_inquiry_text():
    """A general inquiry."""
    return "What departments are available for appointments next week?"


@pytest.fixture
def mock_extracted_schedule():
    """A pre-built ExtractedAppointment for schedule intent (for mocked tests)."""
    from app.schemas import AppointmentIntent, ExtractedAppointment

    return ExtractedAppointment(
        intent=AppointmentIntent.schedule,
        patient_name="John Doe",
        department="cardiology",
        preferred_datetime=datetime(2026, 9, 7, 14, 0),  # Monday
        contact_phone="+15551234567",
        contact_email=None,
        notes=None,
    )


@pytest.fixture
def mock_extracted_cancel():
    """A pre-built ExtractedAppointment for cancel intent."""
    from app.schemas import AppointmentIntent, ExtractedAppointment

    return ExtractedAppointment(
        intent=AppointmentIntent.cancel,
        patient_name="Bob Johnson",
        department=None,
        preferred_datetime=None,
        contact_phone=None,
        contact_email=None,
        notes=None,
    )


@pytest.fixture
def mock_chain(monkeypatch, mock_extracted_schedule):
    """Mock the LCEL chain to return a fixed ExtractedAppointment (no LLM call)."""
    from app import chain

    def fake_invoke(self, inputs, config=None, **kwargs):
        return mock_extracted_schedule

    # Patch the chain's invoke by monkeypatching _build_chain
    def fake_build_chain():
        mock_runnable = MagicMock()
        mock_runnable.invoke = lambda inputs, config=None, **kw: mock_extracted_schedule
        mock_parser = MagicMock()
        return mock_runnable, mock_parser

    monkeypatch.setattr(chain, "_build_chain", fake_build_chain)
    return mock_extracted_schedule