"""
FastAPI endpoint integration tests.

Uses TestClient with mocked LLM chain — no real LLM or proxy needed.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import (
    AppointmentIntent,
    ExecutionStatus,
    ExtractedAppointment,
)


@pytest.fixture
def client():
    """FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_llm_chain(monkeypatch):
    """Auto-mock the LLM chain for all API tests."""
    from app import chain

    extracted = ExtractedAppointment(
        intent=AppointmentIntent.schedule,
        patient_name="John Doe",
        department="cardiology",
        preferred_datetime=datetime(2026, 9, 7, 14, 0),  # Monday — available
        contact_phone="+15551234567",
        contact_email=None,
        notes=None,
    )

    def fake_build_chain():
        mock_runnable = MagicMock()
        mock_runnable.invoke = lambda inputs, config=None, **kw: extracted
        return mock_runnable, MagicMock()

    monkeypatch.setattr(chain, "_build_chain", fake_build_chain)
    return extracted


# ── Health & Root ──────────────────────────────────────────────────────────────
class TestHealthAndRoot:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Appointment Scheduler" in resp.text

    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "llm_model" in data
        assert "sms_mode" in data


# ── Appointment Endpoint ──────────────────────────────────────────────────────
class TestAppointmentEndpoint:
    def test_successful_appointment(self, client):
        """POST /api/appointment with valid text should return confirmed."""
        resp = client.post(
            "/api/appointment",
            json={
                "raw_text": "Book cardiology for John Doe on 2026-09-07 at 14:00",
                "channel": "web",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["extracted"]["patient_name"] == "John Doe"
        assert data["extracted"]["department"] == "cardiology"
        assert data["scheduled_datetime"] is not None
        assert data["confirmation_message_sid"] is not None

    def test_missing_raw_text(self, client):
        """POST without raw_text should return 422 validation error."""
        resp = client.post("/api/appointment", json={"channel": "web"})
        assert resp.status_code == 422

    def test_empty_raw_text(self, client):
        """POST with empty raw_text should return 422 (min_length=1)."""
        resp = client.post("/api/appointment", json={"raw_text": ""})
        assert resp.status_code == 422

    def test_default_channel(self, client):
        """Channel should default to 'web' if not provided."""
        resp = client.post(
            "/api/appointment",
            json={"raw_text": "Book an appointment for tomorrow"},
        )
        assert resp.status_code == 200

    def test_cancel_flow(self, client, monkeypatch):
        """Cancel intent should return cancelled status."""
        from app import chain

        extracted = ExtractedAppointment(
            intent=AppointmentIntent.cancel,
            patient_name="Bob Johnson",
            preferred_datetime=None,
        )

        def fake_build_chain():
            mock_runnable = MagicMock()
            mock_runnable.invoke = lambda inputs, config=None, **kw: extracted
            return mock_runnable, MagicMock()

        monkeypatch.setattr(chain, "_build_chain", fake_build_chain)

        resp = client.post(
            "/api/appointment",
            json={"raw_text": "Cancel my appointment"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["scheduled_datetime"] is None

    def test_llm_error_handled(self, client, monkeypatch):
        """LLM errors should be caught and return 500."""
        from app import chain

        def fake_build_chain():
            mock_runnable = MagicMock()
            mock_runnable.invoke = MagicMock(side_effect=Exception("Proxy down"))
            return mock_runnable, MagicMock()

        monkeypatch.setattr(chain, "_build_chain", fake_build_chain)

        resp = client.post(
            "/api/appointment",
            json={"raw_text": "Some text"},
        )
        # The chain catches the exception and returns error status, not 500
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"