"""Phase 12 — eval harness tests (§15–§16). Mock mode, temp DB per test."""
import json

import pytest

import app.db as db
from evaluation.run_eval import run_eval

TODAY = None  # run_eval defaults to its own fixed TODAY


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "eval.db")
    db.seed(p)
    return p


def test_recall_100_and_zero_false_approvals(db_path):
    out = run_eval(db_path)
    assert out["summary"]["exception_recall"] == 1.0
    assert out["summary"]["false_approvals"] == 0
    assert out["summary"]["decision_accuracy"] == 1.0
    assert out["summary"]["match_accuracy"] == 1.0
    assert out["summary"]["field_errors"] == 0  # mock extraction == ground truth


def test_per_invoice_checks_verified(db_path):
    out = run_eval(db_path)
    # each dangerous sample's specific check fired with the expected status
    assert out["per_invoice"]["d2_qty_mismatch"]["check_expectations"]["quantity"] == "MISMATCH"
    assert out["per_invoice"]["d3_duplicate"]["check_expectations"]["duplicate"] == "DUPLICATE"
    assert out["per_invoice"]["d4_bank_change"]["check_expectations"]["bank_account"] == "HIGH_RISK"
    assert out["per_invoice"]["d5_missing_po"]["check_expectations"]["po_exists"] == "NOT_FOUND"
    assert out["per_invoice"]["d8_currency_mismatch"]["check_expectations"]["currency"] == "FAIL"
    # d9 small is the only one that shouldn't need a human
    assert out["per_invoice"]["d9_small"]["decision"] == "AUTO_APPROVE"
    # d1 normal lands in the manager band (¥850k), so it still needs a human
    assert out["per_invoice"]["d1_normal"]["decision"] == "MANAGER_REVIEW"


def test_report_writes(tmp_path, db_path):
    out = run_eval(db_path)
    (tmp_path / "results.json").write_text(json.dumps(out), encoding="utf-8")
    loaded = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert loaded["summary"] == out["summary"]
    assert "exception_recall" in loaded["summary"]