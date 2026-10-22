# Phase 11.6 — Optional live smoke tests, gated behind RUN_LIVE_TESTS=1.
# Skipped by default (no network); run with:
#   $env:RUN_LIVE_TESTS="1"; .venv\Scripts\python.exe -m pytest tests -v
# Requires local Ollama with tev1:4b pulled AND a working Ollama Cloud key.

import os

import pytest

RUN_LIVE = os.getenv("RUN_LIVE_TESTS") == "1"

requires_live = pytest.mark.skipif(
    not RUN_LIVE, reason="set RUN_LIVE_TESTS=1 to run live smoke tests"
)


@requires_live
def test_live_tev1():
    from services.tev1_service import call_tev1
    questions = {
        "intent": {
            "instructions": "Pick the customer intent.",
            "type": "choice",
            "choices": ["duplicate_charge", "cancel_subscription", "card_declined", "none"],
            "criteria": {
                "duplicate_charge": "billed twice",
                "cancel_subscription": "wants to cancel",
                "card_declined": "card rejected",
                "none": "no billing issue",
            },
        }
    }
    out = call_tev1("Customer was charged twice for the same subscription.", questions)
    answer = out["answers"]["intent"]
    assert answer.get("choice")
    assert out["elapsed_s"] >= 0


@requires_live
def test_live_llm():
    from services.llm_service import call_llm
    out = call_llm("Say OK in one word.")
    assert out["text"].strip()
    assert out["elapsed_s"] >= 0


@requires_live
def test_live_maintai_pipeline(tmp_path, monkeypatch):
    import config.settings as settings
    from datetime import datetime

    from maintai.database import repository as repo
    from maintai.database.connection import get_conn, init_db
    from maintai.maintenance_service import run_decision
    from maintai.models import MachineLimits
    from maintai.prompts import ACTIONS

    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite:///{tmp_path / 'maintai-live.db'}")
    conn = get_conn()
    try:
        init_db(conn)
        repo.upsert_machine(conn, {"machine_id": "LIVE-001",
                                   "machine_type": "test"})
        repo.insert_limit_version(
            conn, "LIVE-001", MachineLimits().model_dump(), datetime.now())
        repo.insert_reading(conn, {
            "machine_id": "LIVE-001", "timestamp": datetime.now(),
            "temperature_c": 68, "vibration_mm_s": 2.4,
            "motor_load_percent": 60, "rpm": 1780, "operating_hours": 1000,
        })
        conn.commit()

        record = run_decision("LIVE-001", conn)
        assert record.tev1 and record.tev1.action in ACTIONS
        assert record.explanation and record.explanation_error is None
        assert conn.execute(
            "SELECT 1 FROM audit_logs WHERE event_type = 'decision_recorded' "
            "AND entity_id = 'LIVE-001'").fetchone()
    finally:
        conn.close()