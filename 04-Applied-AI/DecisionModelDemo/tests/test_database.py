# Phase 2 — database layer tests (plan 2.V): schema, versioning,
# decision round-trip, transactions — against a throwaway tmp_path database.

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

import maintai.database.repository as repo
from maintai.database.connection import db_path, get_conn, init_db
from maintai.models import MachineLimits, SensorReading


def json_loads(text):
    return json.loads(text)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    conn = get_conn()
    init_db(conn)
    yield conn
    conn.close()


def seed_machine(db, machine_id="BRG-001"):
    repo.upsert_machine(db, {"machine_id": machine_id, "machine_type": "Bearing rig"})
    limits = MachineLimits().model_dump()
    repo.insert_limit_version(db, machine_id, limits, datetime(2026, 10, 1))
    return limits


def test_db_path_parses_url():
    assert db_path().name == "maintai.db"


def test_schema_idempotent(db):
    init_db(db)  # second call must not raise
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"machines", "sensor_readings", "machine_limits",
            "maintenance_decisions", "inspections", "audit_logs"} <= tables


def test_machine_upsert_and_list(db):
    seed_machine(db)
    seed_machine(db)  # upsert, no duplicate
    assert len(repo.list_machines(db)) == 1
    assert repo.get_machine(db, "BRG-001")["machine_type"] == "Bearing rig"


def test_machine_team_and_edit(db):
    """Registry edit path (plan 11.1): upsert changes fields, team persists."""
    seed_machine(db)
    repo.upsert_machine(db, {"machine_id": "BRG-001", "machine_name": "Rig A",
                             "team": "Rotating equipment", "location": "Bay 9",
                             "status": "mandatory_escalation"})
    row = repo.get_machine(db, "BRG-001")
    assert (row["machine_name"], row["team"], row["location"],
            row["status"]) == ("Rig A", "Rotating equipment", "Bay 9",
                               "mandatory_escalation")


def test_reading_roundtrip_and_window(db):
    seed_machine(db)
    t0 = datetime.now().replace(microsecond=0)
    for h in range(5):
        db.execute("UPDATE machines SET status = 'active' WHERE machine_id = 'BRG-001'")
        r = dict(machine_id="BRG-001", timestamp=t0 - timedelta(hours=4 - h),
                 temperature_c=70 + h, vibration_mm_s=3.0,
                 motor_load_percent=70.0, rpm=1800.0,
                 operating_hours=1200.0 + h, data_source="synthetic")
        repo.insert_reading(db, r)
    rows = repo.readings_window(db, "BRG-001", limit=3)
    assert [r["temperature_c"] for r in rows] == [72, 73, 74]  # oldest-first
    assert repo.latest_reading(db, "BRG-001")["temperature_c"] == 74


def test_duplicate_reading_ignored(db):
    seed_machine(db)
    r = dict(machine_id="BRG-001", timestamp=datetime.now().replace(microsecond=0),
             temperature_c=70.0, data_source="synthetic")
    repo.insert_reading(db, r)
    repo.insert_reading(db, r)
    n = db.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
    assert n == 1


def test_limit_versioning_and_as_of(db):
    seed_machine(db)
    repo.insert_limit_version(
        db, "BRG-001", MachineLimits(temperature_critical=80).model_dump(),
        datetime(2026, 10, 15))
    now = repo.active_limits(db, "BRG-001")
    three_days_ago = repo.active_limits(db, "BRG-001", as_of=datetime(2026, 10, 14))
    assert now["temperature_critical"] == 80          # newest version active
    assert three_days_ago["temperature_critical"] == 90  # earlier version reproduced
    assert now["version"] == 2 and now["effective_to"] is None
    assert three_days_ago["effective_to"] is not None   # superseded


def test_list_limit_versions(db):
    """Registry history view (plan 11.1): newest first, versions + supersession."""
    seed_machine(db)
    repo.insert_limit_version(
        db, "BRG-001", MachineLimits(vibration_critical=5.0).model_dump(),
        datetime(2026, 10, 15))
    versions = repo.list_limit_versions(db, "BRG-001")
    assert [v["version"] for v in versions] == [2, 1]  # newest first
    assert versions[0]["effective_to"] is None          # current version open
    assert versions[1]["effective_to"] is not None      # v1 superseded
    assert versions[0]["vibration_critical"] == 5.0


def test_decision_roundtrip(db):
    seed_machine(db)
    decision = {
        "machine_id": "BRG-001",
        "input_snapshot": {"temperature_c": 94.0, "limits_version": 1},
        "rule_alerts": ["Temperature above configured limit"],
        "tev1_action": "urgent_maintenance",
        "tev1_probabilities": {"urgent_maintenance": 0.9},
        "tev1_confidence": 0.91,
        "policy_outcome": "urgent_human_review",
        "llm_explanation": None,
        "model_name": "tev1:4b",
        "policy_version": "1",
        "latency_ms": 846.0,
        "error_status": None,
    }
    decision_id = repo.insert_decision(db, decision)
    row = repo.list_decisions(db, "BRG-001")[0]
    assert row["id"] == decision_id
    assert row["policy_outcome"] == "urgent_human_review"
    assert json_loads(row["input_snapshot"])["temperature_c"] == 94.0
    assert row["tev1_confidence"] == 0.91
    # prob/explanation fields stay NULL, never fabricated
    repo.insert_decision(db, {**decision, "tev1_probabilities": None,
                              "llm_explanation": None})
    row2 = repo.list_decisions(db, "BRG-001")[1]
    assert row2["tev1_probabilities"] is None and row2["llm_explanation"] is None


def test_inspection_and_audit(db):
    seed_machine(db)
    repo.insert_inspection(db, {"machine_id": "BRG-001",
                                "inspection_date": "2026-10-19",
                                "inspector": "Priya", "findings": "bearing wear"})
    repo.record_audit(db, "priya", "inspection_recorded", "machine", "BRG-001",
                      {"decision_id": 3})
    assert repo.list_inspections(db, "BRG-001")[0]["inspector"] == "Priya"
    assert repo.list_audit(db, "BRG-001")[0]["user_id"] == "priya"
    assert repo.pending_inspections(db) == 0  # that decision_id is now closed


def test_transaction_rollback(db):
    seed_machine(db)
    with pytest.raises(sqlite3.IntegrityError):
        with db:  # FK violation -> implicit rollback of the insert
            repo.record_audit(db, "u", "x", "machine", "BRG-001")
            db.execute("INSERT INTO inspections (machine_id, inspection_date) "
                       "VALUES ('GHOST', '2026-10-19')")
    assert db.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 0


def test_dashboard_kpis(db):
    seed_machine(db)
    for _ in range(2):
        repo.insert_decision(db, {
            "machine_id": "BRG-001",
            "input_snapshot": {}, "rule_alerts": [],
            "policy_outcome": "urgent_human_review", "model_name": "tev1:4b",
        })
    kpis = repo.dashboard_kpis(db)
    assert kpis["registered_machines"] == 1
    assert kpis["machines_requiring_review"] == 1
    assert kpis["recent_decisions"] == 2
    assert kpis["active_high_priority_alerts"] == 1
    assert sorted((r[0], r[1]) for r in repo.action_counts(db)) == [
        ("urgent_human_review", 2)]


def test_machine_action_status_flags_latest_decisions(db):
    seed_machine(db, "URGENT-1")
    repo.upsert_machine(db, {"machine_id": "MONITOR-1"})
    seed_machine(db, "INSPECT-1")
    repo.upsert_machine(db, {"machine_id": "UNASSESSED-1"})
    for machine_id, action, outcome in (
            ("URGENT-1", "monitor", "urgent_human_review"),
            ("MONITOR-1", "monitor", "policy_auto_decision"),
            ("INSPECT-1", "inspect", "policy_auto_decision")):
        repo.insert_decision(db, {
            "machine_id": machine_id, "input_snapshot": {}, "rule_alerts": [],
            "tev1_action": action, "policy_outcome": outcome})

    statuses = {row["machine_id"]: row
                for row in repo.machine_action_statuses(db)}
    assert statuses["URGENT-1"]["status"] == "Action required"
    assert statuses["URGENT-1"]["flag"] == "🔴"
    assert statuses["MONITOR-1"]["status"] == "No action required"
    assert statuses["MONITOR-1"]["flag"] == "🟢"
    assert statuses["INSPECT-1"]["status"] == "Wait & observe"
    assert statuses["INSPECT-1"]["flag"] == "🟡"
    assert statuses["UNASSESSED-1"]["status"] == "Not assessed"
    assert statuses["UNASSESSED-1"]["flag"] == "⚪"

    decision_id = repo.insert_decision(db, {
        "machine_id": "MONITOR-1", "input_snapshot": {}, "rule_alerts": [],
        "tev1_action": "inspect", "policy_outcome": "human_review_required"})
    repo.record_audit(db, "Engineer", "inspection_recorded", "machine",
                      "MONITOR-1", {"decision_id": decision_id,
                                    "resolution_status": "closed"})
    assert {r["machine_id"]: r for r in repo.machine_action_statuses(db)
            }["MONITOR-1"]["status"] == "Wait & observe"


def test_reviewed_machine_leaves_requiring_review_kpi(db):
    """Closed loop (plan 10.2/10.3): recording a linked inspection clears the
    machine's live 'requiring review' KPI; unrelated decisions stay open."""
    seed_machine(db)
    repo.upsert_machine(db, {"machine_id": "MIX-001"})
    reviewed = repo.insert_decision(db, {
        "machine_id": "BRG-001", "input_snapshot": {}, "rule_alerts": [],
        "policy_outcome": "urgent_human_review"})
    repo.insert_decision(db, {
        "machine_id": "MIX-001", "input_snapshot": {}, "rule_alerts": [],
        "policy_outcome": "urgent_human_review"})
    assert repo.dashboard_kpis(db)["machines_requiring_review"] == 2

    repo.record_audit(db, "priya", "inspection_recorded", "machine", "BRG-001",
                      {"decision_id": reviewed})
    kpis = repo.dashboard_kpis(db)
    assert kpis["machines_requiring_review"] == 1  # MIX-001 still open
    assert kpis["pending_inspections"] == 1        # MIX-001's open decision
    assert kpis["active_high_priority_alerts"] == 2  # historical alert intact


def test_pending_inspections_ignores_malformed_audit_details(db):
    seed_machine(db)
    did = repo.insert_decision(db, {
        "machine_id": "BRG-001", "input_snapshot": {}, "rule_alerts": [],
        "policy_outcome": "urgent_human_review"})
    for details in ('{"decision_id": null}', 'not json', '[1]'):
        repo.record_audit(db, "x", "inspection_recorded", "machine", "BRG-001",
                          details)
    assert repo.dashboard_kpis(db)["pending_inspections"] == did  # still open


def test_sql_is_parameterized():
    """Guard the no-f-string-SQL rule. Whitelist: the limits insert builds its
    placeholder list from LIMIT_FIELDS; KPI day args interpolate ? params."""
    import inspect

    bad = []
    for name, fn in inspect.getmembers(repo, inspect.isfunction):
        for i, line in enumerate(inspect.getsource(fn).splitlines(), 1):
            if "execute(" in line and "f\"" in line and "LIMIT_FIELDS" not in line:
                bad.append(f"{name}:{i}")
    assert bad == []