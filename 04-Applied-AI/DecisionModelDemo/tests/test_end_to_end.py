# Phase 7 — end-to-end pipeline tests (plan 7.V, subset of spec §13 scenarios).
# Tev1/LLM mocked via injectable callables; real database in tmp_path.

import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.maintenance_service import PolicyOutcome, run_decision
from maintai.models import MachineLimits
from maintai.seed import seed

# Real seed data: BRG-001 ends near critical temps; MIX-001 stays normal.
CANNED_INSPECT = {"model": "tev1:4b", "elapsed_s": 0.9, "answers": {
    "maintenance_action": {"type": "choice", "choice": "inspect",
                           "probabilities": {"inspect": 0.8, "monitor": 0.2},
                           "confidence": 0.8},
    "anomaly_present": {"type": "noul", "noul": 0.9},
    "severity": {"type": "score", "score": 2.4, "legend": {"2": "Moderate"},
                 "probabilities": {"2": 0.6}, "confidence": 0.7},
}}
CANNED_MONITOR = {**CANNED_INSPECT, "answers": {
    "maintenance_action": {"type": "choice", "choice": "monitor",
                           "probabilities": {"monitor": 0.98}, "confidence": 0.99},
    "anomaly_present": {"type": "noul", "noul": 0.05},
    "severity": {"type": "score", "score": 0.4, "legend": {"0": "Normal"},
                 "probabilities": {"0": 0.9}, "confidence": 0.9},
}}

LIMITS = MachineLimits().model_dump()


def add_machine_reading(db, machine_id, **values):
    repo.upsert_machine(db, {"machine_id": machine_id, "machine_type": "test"})
    repo.insert_limit_version(db, machine_id, LIMITS, datetime.now())
    repo.insert_reading(db, {
        "machine_id": machine_id, "timestamp": datetime.now(),
        "temperature_c": 68, "vibration_mm_s": 2.4,
        "motor_load_percent": 60, "rpm": 1780, "operating_hours": 1000,
        **values,
    })
    db.commit()


def assert_decision_persisted(db, record, expected_outcome):
    assert record.outcome.outcome == expected_outcome
    row = db.execute(
        "SELECT policy_outcome FROM maintenance_decisions WHERE id = ?",
        (record.decision_id,)).fetchone()
    assert row["policy_outcome"] == expected_outcome
    audit = db.execute(
        "SELECT details FROM audit_logs WHERE event_type = 'decision_recorded' "
        "AND entity_id = ? ORDER BY id DESC LIMIT 1",
        (record.machine_id,)).fetchone()
    assert audit is not None
    assert json.loads(audit["details"])["decision_id"] == record.decision_id


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    import config.settings as settings
    path = tmp_path_factory.mktemp("db") / "e2e.db"
    settings.DATABASE_URL = f"sqlite:///{path}"
    seed()
    conn = get_conn()
    yield conn
    conn.close()
    settings.DATABASE_URL = "sqlite:///maintai.db"  # restore for other modules


def test_critical_machine_goes_urgent(db):
    record = run_decision("PMP-001", db, run_llm=False)  # spiked past critical at the end
    assert record.outcome.outcome == PolicyOutcome.URGENT
    assert record.outcome.final_action == "urgent_maintenance"
    assert record.report.critical_breaches
    # persisted + audited
    decision = db.execute(
        "SELECT * FROM maintenance_decisions WHERE id = ?",
        (record.decision_id,)).fetchone()
    assert decision["policy_outcome"] == PolicyOutcome.URGENT
    assert decision["policy_version"] == "1"
    audit = db.execute(
        "SELECT * FROM audit_logs WHERE event_type = 'decision_recorded' "
        "AND entity_id = 'PMP-001'").fetchone()
    assert audit is not None
    assert_decision_persisted(db, record, PolicyOutcome.URGENT)


def test_normal_machine_accepts_monitor(db):
    record = run_decision("MIX-001", db, run_tev1=lambda s, q: CANNED_MONITOR,
                          run_llm=False)
    assert record.outcome.final_action == "monitor"
    assert record.tev1.action_confidence == 0.99
    assert_decision_persisted(db, record, PolicyOutcome.AUTO)


@pytest.mark.parametrize(("machine_id", "values", "expected_alert"), [
    ("E2E-TEMP-WARN", {"temperature_c": 80}, "Temperature warning"),
    ("E2E-VIB-WARN", {"vibration_mm_s": 4.0}, "Vibration warning"),
    ("E2E-MULTI-WARN", {"temperature_c": 80, "vibration_mm_s": 4.0,
                         "motor_load_percent": 80}, None),
])
def test_warning_scenarios_are_reported_and_persisted(
        db, machine_id, values, expected_alert):
    add_machine_reading(db, machine_id, **values)
    record = run_decision(machine_id, db, run_tev1=lambda s, q: CANNED_MONITOR,
                          run_llm=False)
    assert record.outcome.outcome == PolicyOutcome.AUTO
    if expected_alert:
        assert any(expected_alert in alert for alert in record.report.alerts)
    else:
        assert len(record.report.alerts) >= 3
    assert_decision_persisted(db, record, PolicyOutcome.AUTO)


def test_missing_sensor_data_requires_review_and_is_persisted(db):
    add_machine_reading(db, "E2E-MISSING", vibration_mm_s=None)
    record = run_decision("E2E-MISSING", db, run_tev1=lambda s, q: CANNED_MONITOR,
                          run_llm=False)
    assert record.error_status == "missing_data"
    assert_decision_persisted(db, record, PolicyOutcome.DATA_REVIEW)


def test_stale_reading_requires_review_and_is_persisted(db):
    add_machine_reading(db, "E2E-STALE",
                        timestamp=datetime.now() - timedelta(days=1))
    record = run_decision("E2E-STALE", db, run_tev1=lambda s, q: CANNED_MONITOR,
                          run_llm=False)
    assert record.error_status == "stale"
    assert_decision_persisted(db, record, PolicyOutcome.DATA_REVIEW)


def test_tev1_timeout_is_never_safe(db):
    from services.tev1_service import Tev1Error

    def broken(state, questions):
        raise Tev1Error("Tev1 decision model timed out. Try again.")

    record = run_decision("MIX-001", db, run_tev1=broken, run_llm=False)
    assert record.outcome.final_action == "insufficient_data"
    assert record.error_status and "decision_unavailable" in record.error_status
    # the failure is persisted with a review-required outcome (spec1 §14)
    row = db.execute("SELECT policy_outcome, error_status FROM maintenance_decisions"
                     " WHERE id = ?", (record.decision_id,)).fetchone()
    assert row["policy_outcome"] == PolicyOutcome.UNAVAILABLE
    assert_decision_persisted(db, record, PolicyOutcome.UNAVAILABLE)


def test_low_confidence_requires_review_and_is_persisted(db):
    add_machine_reading(db, "E2E-LOW-CONFIDENCE")
    response = deepcopy(CANNED_MONITOR)
    response["answers"]["maintenance_action"]["confidence"] = 0.2
    record = run_decision("E2E-LOW-CONFIDENCE", db,
                          run_tev1=lambda s, q: response, run_llm=False)
    assert "below review threshold" in record.outcome.reason
    assert_decision_persisted(db, record, PolicyOutcome.REVIEW)


def test_conflicting_model_output_requires_review_and_is_persisted(db):
    add_machine_reading(db, "E2E-CONFLICT")
    response = deepcopy(CANNED_MONITOR)
    response["answers"]["anomaly_present"]["noul"] = 0.95
    record = run_decision("E2E-CONFLICT", db, run_tev1=lambda s, q: response,
                          run_llm=False)
    assert "conflicts" in record.outcome.reason
    assert_decision_persisted(db, record, PolicyOutcome.REVIEW)


def test_invalid_tev1_response_is_persisted_as_review_required(db):
    record = run_decision("MIX-001", db,
                          run_tev1=lambda state, questions: {
                              "answers": {"maintenance_action": "invalid"}},
                          run_llm=False)
    assert record.outcome.outcome == PolicyOutcome.UNAVAILABLE
    assert record.error_status == (
        "decision_unavailable: Tev1 returned an invalid response.")
    row = db.execute(
        "SELECT policy_outcome, error_status FROM maintenance_decisions WHERE id = ?",
        (record.decision_id,)).fetchone()
    assert row["policy_outcome"] == PolicyOutcome.UNAVAILABLE
    assert row["error_status"] == record.error_status


def test_invalid_stored_reading_is_persisted_as_review_required(db):
    from datetime import datetime

    repo.upsert_machine(db, {"machine_id": "INVALID-1", "machine_type": "test"})
    repo.insert_limit_version(db, "INVALID-1", {
        "temperature_warning": 75, "temperature_critical": 90,
        "vibration_warning": 3.5, "vibration_critical": 4.5,
        "motor_load_warning": 75, "motor_load_critical": 85,
    }, datetime.now())
    repo.insert_reading(db, {
        "machine_id": "INVALID-1", "timestamp": datetime.now(),
        "temperature_c": 999, "vibration_mm_s": 1, "motor_load_percent": 20,
        "rpm": 100, "operating_hours": 10,
    })
    db.commit()

    record = run_decision("INVALID-1", db, run_llm=False)
    assert record.outcome.outcome == PolicyOutcome.DATA_REVIEW
    assert record.error_status == "invalid"
    saved = db.execute(
        "SELECT policy_outcome, error_status FROM maintenance_decisions WHERE id = ?",
        (record.decision_id,)).fetchone()
    assert saved["policy_outcome"] == PolicyOutcome.DATA_REVIEW
    assert saved["error_status"] == "invalid"


def test_review_requires_engineer_and_only_closed_reviews_clear_pending(db):
    from maintai.maintenance_service import record_inspection

    before = repo.pending_inspections(db)
    record = run_decision("PMP-001", db, run_llm=False)
    assert repo.pending_inspections(db) == before + 1
    inspection = {"inspection_date": "2026-10-20", "inspector": "Casey",
                  "findings": "Checked bearing", "resolution_status": "open"}
    with pytest.raises(PermissionError):
        record_inspection(db, "PMP-001", record.decision_id, inspection, "Viewer")
    assert repo.pending_inspections(db) == before + 1

    open_id = record_inspection(db, "PMP-001", record.decision_id, inspection,
                                "Engineer")
    assert repo.pending_inspections(db) == before + 1
    audit = db.execute(
        "SELECT timestamp, user_id, details FROM audit_logs "
        "WHERE event_type = 'inspection_recorded' AND user_id = 'Casey' "
        "AND details LIKE ?", (f'%"inspection_id": {open_id}%',)).fetchone()
    assert audit["timestamp"] and audit["user_id"] == "Casey"
    assert json.loads(audit["details"])["reviewer_role"] == "Engineer"

    record_inspection(db, "PMP-001", record.decision_id,
                      {**inspection, "resolution_status": "closed"}, "Engineer")
    assert repo.pending_inspections(db) == before


def test_input_snapshot_keeps_limits_version(db):
    record = run_decision("BRG-001", db, run_tev1=lambda s, q: CANNED_INSPECT,
                          run_llm=False)
    decision = db.execute("SELECT input_snapshot FROM maintenance_decisions"
                          " WHERE id = ?", (record.decision_id,)).fetchone()
    import json
    snapshot = json.loads(decision["input_snapshot"])
    assert snapshot["limits"]["temperature"]["critical"] == 90
    assert snapshot["machine_id"] == "BRG-001"


def test_unknown_machine_and_no_data(db):
    import config.settings as settings
    original = settings.DATABASE_URL
    with pytest.raises(ValueError, match="Unknown machine"):
        run_decision("GHOST-999", db)
    # a machine row with no readings:
    from maintai.database import repository as repo
    repo.upsert_machine(db, {"machine_id": "EMPTY-1"})
    db.commit()
    with pytest.raises(ValueError, match="No sensor readings"):
        run_decision("EMPTY-1", db)
    assert settings.DATABASE_URL == original


def test_pipeline_runs_explanation_by_default(db, monkeypatch):
    """run_decision with no run_llm: explanation service called, fallback shape."""
    recorded = {}

    def fake_explanation(record, values, limits, history_lines):
        recorded["values"] = values
        return {"summary": "s", "evidence": [], "recommended_checks": [],
                "limitations": []}, None

    import maintai.explanation_service as esvc
    monkeypatch.setattr(esvc, "generate_explanation", fake_explanation)
    record = run_decision("MIX-001", db, run_tev1=lambda s, q: CANNED_MONITOR)
    assert record.explanation["summary"] == "s" and record.explanation_error is None
    row = db.execute("SELECT llm_explanation FROM maintenance_decisions"
                     " WHERE id = ?", (record.decision_id,)).fetchone()
    assert json.loads(row["llm_explanation"])["summary"] == "s"
    assert "temperature_c" in recorded["values"]  # evidence passed through


def test_llm_failure_is_recorded_without_changing_policy(db, monkeypatch):
    import maintai.explanation_service as esvc

    monkeypatch.setattr(
        esvc, "generate_explanation",
        lambda *args: ({"summary": "Fallback", "evidence": []},
                       "Ollama Cloud unavailable"))
    record = run_decision("MIX-001", db, run_tev1=lambda s, q: CANNED_MONITOR)
    assert record.outcome.outcome == PolicyOutcome.AUTO
    assert record.error_status == "llm_explanation_unavailable"
    row = db.execute(
        "SELECT policy_outcome, error_status FROM maintenance_decisions WHERE id = ?",
        (record.decision_id,)).fetchone()
    assert row["policy_outcome"] == PolicyOutcome.AUTO
    assert row["error_status"] == "llm_explanation_unavailable"
    assert_decision_persisted(db, record, PolicyOutcome.AUTO)


def test_csv_with_invalid_rows_quarantines_them_and_persists_valid_decision(db):
    from maintai.import_core import classify_rows, parse_csv

    machine_id = "E2E-CSV"
    repo.upsert_machine(db, {"machine_id": machine_id, "machine_type": "test"})
    repo.insert_limit_version(db, machine_id, LIMITS, datetime.now())
    stamp = datetime.now().isoformat(sep=" ")
    text = (
        "machine_id,timestamp,temperature_c,vibration_mm_s,motor_load_percent,"
        "rpm,operating_hours\n"
        f"{machine_id},{stamp},68,2.4,60,1780,1000\n"
        f"{machine_id},{stamp},hot,2.4,60,1780,1000\n"
    )
    report = classify_rows(parse_csv(text), source_name="scenario.csv")
    assert len(report["valid"]) == 1 and len(report["quarantined"]) == 1

    with db:
        repo.insert_reading(db, report["valid"][0])
        repo.record_audit(db, "test", "data_imported", "machine", "scenario.csv",
                          {"valid": 1, "rejected": 1})
    record = run_decision(machine_id, db, run_tev1=lambda s, q: CANNED_MONITOR,
                          run_llm=False)
    assert_decision_persisted(db, record, PolicyOutcome.AUTO)
    imported = db.execute(
        "SELECT details FROM audit_logs WHERE event_type = 'data_imported' "
        "AND entity_id = 'scenario.csv'").fetchone()
    assert json.loads(imported["details"])["rejected"] == 1