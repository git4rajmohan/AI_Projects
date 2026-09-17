"""Phase 8 — orchestrator tests: full pipeline per demo scenario + reviewer actions.

Mock extraction (default config) + a fresh seeded SQLite per test. TODAY is fixed
so date-sanity checks are deterministic (ground truth dates are 2026-09-10..12).
"""
from datetime import date

import pytest

import app.db as db
from app.policy.engine import AUTO_APPROVE, EXCEPTION, FINANCE_REVIEW, REJECT
from app.workflow import orchestrator as wf
from app.workflow.orchestrator import apply_review_action, process_invoice

TODAY = date(2026, 9, 15)
SAMPLES = "data/invoices"


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "wf.db")
    db.seed(p)
    return p


def run(name, db_path, **kw):
    return process_invoice(f"{SAMPLES}/{name}.pdf", today=TODAY, db_path=db_path, **kw)


def test_demo1_normal_manager_review(db_path):
    # 850k >= auto_approve_limit(100k) → manager band, not auto-approve (plan note updated)
    r = run("d1_normal", db_path)
    assert r.decision.decision == "MANAGER_REVIEW"
    assert r.status == wf.IN_REVIEW
    with db.get_conn(db_path) as conn:
        row = conn.execute("SELECT status FROM invoices WHERE invoice_id='d1_normal'").fetchone()
    assert row["status"] == wf.IN_REVIEW


def test_demo9_small_auto_approves(db_path):
    r = run("d9_small", db_path)
    assert r.decision.decision == AUTO_APPROVE
    assert r.status == wf.AUTO_APPROVED
    # no exception row for a clean invoice
    with db.get_conn(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM exceptions").fetchone()["c"] == 0


def test_demo2_qty_mismatch_exception_with_row(db_path):
    r = run("d2_qty_mismatch", db_path)
    assert r.decision.decision == EXCEPTION
    assert r.status == wf.IN_REVIEW
    with db.get_conn(db_path) as conn:
        ex = conn.execute("SELECT * FROM exceptions WHERE invoice_id='d2_qty_mismatch'").fetchone()
    assert ex is not None and ex["status"] == "open"


def test_demo3_duplicate_blocked_never_stored(db_path):
    r = run("d3_duplicate", db_path)
    assert r.decision.decision == REJECT
    assert r.status == wf.REJECTED
    # the repeat upload must not have created its own invoice row (idempotency, 8.6)
    with db.get_conn(db_path) as conn:
        rows = conn.execute("SELECT invoice_id FROM invoices WHERE invoice_number='INV-10025'").fetchall()
    assert [x["invoice_id"] for x in rows] == ["inv_seed_1"]
    assert conn.execute("SELECT COUNT(*) c FROM review_actions").fetchone()["c"] == 0


def test_demo3_reupload_after_processed_is_still_blocked(db_path):
    # second upload of an invoice the pipeline itself already stored → also duplicate
    run("d1_normal", db_path)
    r = run("d3_duplicate", db_path)  # INV-10025 (seeded, paid)
    assert r.decision.decision == REJECT


def test_demo4_bank_change_high_risk_in_review(db_path):
    r = run("d4_bank_change", db_path)
    assert r.decision.rule_id == "R002-bank-change"
    assert r.status == wf.IN_REVIEW
    with db.get_conn(db_path) as conn:
        ex = conn.execute("SELECT type, severity FROM exceptions WHERE invoice_id='d4_bank_change'").fetchone()
    assert ex["type"] == "high_risk" and ex["severity"] == "high"


def test_demo5_missing_po_exception(db_path):
    r = run("d5_missing_po", db_path)
    assert r.decision.rule_id == "R003-missing-po"
    assert r.status == wf.IN_REVIEW


def test_demo6_low_confidence_human_review(db_path):
    r = run("d6_low_confidence", db_path)
    assert r.decision.rule_id == "R005-low-confidence"
    assert r.decision.decision == "HUMAN_REVIEW"
    assert r.status == wf.IN_REVIEW


def test_demo7_high_value_finance_review(db_path):
    r = run("d7_high_value", db_path)
    assert r.decision.decision == FINANCE_REVIEW
    assert r.status == wf.IN_REVIEW


def test_correct_resumes_and_decides(db_path):
    # Demo 5 flow: missing PO → reviewer corrects the PO number → pipeline re-runs
    run("d5_missing_po", db_path)
    status = apply_review_action("d5_missing_po", "reviewer-1", "correct",
                                 corrections={"po_number": "PO-20003"},
                                 today=TODAY, db_path=db_path)
    assert status == wf.IN_REVIEW  # 1.2M JPY total → manager/finance band after fix
    with db.get_conn(db_path) as conn:
        ex = conn.execute("SELECT status FROM exceptions WHERE invoice_id='d5_missing_po'").fetchone()
        acts = conn.execute("SELECT reviewer, action FROM review_actions WHERE invoice_id='d5_missing_po'").fetchall()
        st = conn.execute("SELECT status FROM invoices WHERE invoice_id='d5_missing_po'").fetchone()
    assert ex["status"] == "resolved"  # missing-PO exception cleared by the correction
    assert [(a["reviewer"], a["action"]) for a in acts] == [("reviewer-1", "correct")]
    assert st["status"] == wf.IN_REVIEW


def test_correct_low_confidence_then_approve(db_path):
    run("d6_low_confidence", db_path)
    # correcting the total only verifies that field; the rest of the garbled doc keeps
    # its capped confidence → R005 still fires → stays in review (safe by design)
    status = apply_review_action("d6_low_confidence", "rev", "correct",
                                 corrections={"total_amount": 40000}, today=TODAY, db_path=db_path)
    assert status == wf.IN_REVIEW
    # reviewer, having seen the document, disposes it manually
    status = apply_review_action("d6_low_confidence", "rev", "approve", "verified against scan",
                                 today=TODAY, db_path=db_path)
    assert status == wf.APPROVED
    with db.get_conn(db_path) as conn:
        acts = conn.execute("SELECT action FROM review_actions WHERE invoice_id='d6_low_confidence'").fetchall()
    assert [a["action"] for a in acts] == ["correct", "approve"]


def test_request_info_and_unknown_action(db_path):
    run("d2_qty_mismatch", db_path)
    assert apply_review_action("d2_qty_mismatch", "rev", "request_info", "need GR doc",
                               db_path=db_path) == wf.INFO_REQUESTED
    with db.get_conn(db_path) as conn:
        st = conn.execute("SELECT status FROM invoices WHERE invoice_id='d2_qty_mismatch'").fetchone()
    assert st["status"] == wf.INFO_REQUESTED
    try:
        apply_review_action("d2_qty_mismatch", "rev", "teleport", db_path=db_path)
        assert False, "unknown action must raise"
    except ValueError:
        pass


def test_unknown_invoice_returns_none(db_path):
    assert apply_review_action("nope", "rev", "approve", db_path=db_path) is None


def test_state_transitions_recorded_in_order(db_path):
    run("d9_small", db_path)
    with db.get_conn(db_path) as conn:
        stages = [r["stage"] for r in conn.execute(
            "SELECT stage FROM audit_events WHERE invoice_id='d9_small' ORDER BY event_id")]
    assert stages == ["received", "extracted", "validated", "matched",
                      "policy_decided", "auto_approved"]