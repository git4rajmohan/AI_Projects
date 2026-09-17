"""Phase 9 — audit reconstruction tests: the decision story from the log alone."""
from datetime import date

import pytest

import app.db as db
from app.audit.recorder import build_audit_report, explain
from app.workflow.orchestrator import (IN_REVIEW, apply_review_action, process_invoice)

TODAY = date(2026, 9, 15)


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "audit.db")
    db.seed(p)
    return p


def run(name, db_path, **kw):
    return process_invoice(f"data/invoices/{name}.pdf", today=TODAY, db_path=db_path, **kw)


def test_demo1_audit_report_ordered_and_complete(db_path):
    run("d9_small", db_path)
    report = build_audit_report("d9_small", db_path)
    stages = [e["stage"] for e in report["events"]]
    # ≥7 ordered events: received, extracted, validated, matched, policy_decided, outcome
    assert stages[0] == "received" and stages[-1] == "auto_approved"
    assert len(stages) >= 6
    # JSON-serializable end to end
    import json
    json.dumps(report)  # must not raise
    # reconstruction from log alone: extracted fields + confidence present
    extracted = next(e for e in report["events"] if e["stage"] == "extracted")["payload"]
    assert extracted["invoice_number"] == "INV-10032"
    assert extracted["field_confidence"]["total_amount"] > 0.5
    # policy decision with rule_id
    dec = next(e for e in report["events"] if e["stage"] == "policy_decided")["payload"]["decision"]
    assert dec["rule_id"] == "R008-auto-approve"


def test_reviewer_action_recorded_with_timestamp(db_path):
    run("d2_qty_mismatch", db_path)
    apply_review_action("d2_qty_mismatch", "alice", "approve", "GR verified", db_path=db_path)
    report = build_audit_report("d2_qty_mismatch", db_path)
    (ra,) = report["review_actions"]
    assert ra["reviewer"] == "alice" and ra["action"] == "approve"
    assert ra["comments"] == "GR verified" and ra["timestamp"]
    # the audit event stream also carries it
    assert "review" in [e["stage"] for e in report["events"]]


def test_explain_payload_shapes(db_path):
    run("d4_bank_change", db_path)
    report = build_audit_report("d4_bank_change", db_path)
    x = __import__("app.audit.recorder", fromlist=["explain"]).explain(report)
    assert x["decision"] == "HUMAN_REVIEW" and x["rule_id"] == "R002-bank-change"
    assert any("bank account changed" in w for w in x["why"])
    assert x["extracted"]["total_amount"] == 850_000
    assert {c["name"] for c in x["validated"]} >= {"vendor_exists", "bank_account", "arithmetic"}
    assert {c["name"] for c in x["matched"]} >= {"po_exists", "quantity"}
    assert x["final_status"] == IN_REVIEW


def test_unknown_invoice_returns_none(db_path):
    assert build_audit_report("ghost", db_path) is None


def test_exception_reconstruction(db_path):
    run("d5_missing_po", db_path)
    report = build_audit_report("d5_missing_po", db_path)
    assert report["exceptions"][0]["type"] == "policy_exception"
    assert "PO-99999" in report["exceptions"][0]["reason"]