"""Phase 10 — API tests (§10.5). FastAPI TestClient, fresh seeded SQLite per test.

The lazy DB seam: db.get_conn() reads settings.db_path at call time, so each test
points that one setting at its tmp DB and every db.* call (pipeline + routers)
follows. No dependency-injection plumbing needed.
"""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as db
from app.api.main import app
from app.config import settings

SAMPLES = Path("data/invoices")
client = TestClient(app)


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    p = tmp_path / "api.db"
    db.seed(str(p))
    monkeypatch.setattr(settings, "db_path", str(p))
    return str(p)


def _upload(name: str) -> dict:
    """Upload a copy of a shipped sample; mock extraction resolves its ground truth."""
    pdf = (SAMPLES / f"{name}.pdf").read_bytes()
    r = client.post("/invoices/upload", files={"file": (f"{name}.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_demo9_auto_approves(api_db):
    out = _upload("d9_small")
    assert out["invoice_id"] == "d9_small"
    assert out["status"] == "auto_approved"
    assert out["decision"] == "AUTO_APPROVE"
    assert out["rule_id"] == "R008-auto-approve"


def test_upload_demo1_manager_band(api_db):
    out = _upload("d1_normal")  # ¥850k ≥ ¥100k → manager band (plan note: not auto-approve)
    assert out["status"] == "in_review"
    assert out["decision"] == "MANAGER_REVIEW"


def test_upload_demo4_bank_change_in_review(api_db):
    out = _upload("d4_bank_change")
    assert out["decision"] == "HUMAN_REVIEW"
    assert out["rule_id"] == "R002-bank-change"


def test_upload_corrupt_pdf_422_with_exception_row(api_db):
    r = client.post("/invoices/upload",
                    files={"file": ("bad.pdf", b"this is not a pdf", "application/pdf")})
    assert r.status_code == 422
    with db.get_conn() as conn:
        row = conn.execute("SELECT type, status FROM exceptions WHERE invoice_id='bad'").fetchone()
    assert row is not None and row["type"] == "ingest_error" and row["status"] == "open"


def test_list_invoices_filter_by_status(api_db):
    _upload("d9_small")
    _upload("d1_normal")
    rows = client.get("/invoices").json()
    assert {r["invoice_id"] for r in rows} >= {"d9_small", "d1_normal"}
    review = client.get("/invoices", params={"status": "in_review"}).json()
    assert [r["invoice_id"] for r in review] == ["d1_normal"]


def test_invoice_detail_sections(api_db):
    _upload("d2_qty_mismatch")
    d = client.get("/invoices/d2_qty_mismatch").json()
    assert d["status"] == "in_review"
    assert d["extraction"]["invoice_number"] == "INV-10027"
    assert {c["name"] for c in d["validation"]} >= {"vendor_active", "duplicate", "required_fields"}
    assert {c["name"] for c in d["match"]} >= {"po_exists", "quantity"}
    assert d["decision"] == "EXCEPTION" and d["reasons"]
    assert any(e["type"] == "policy_exception" for e in d["exceptions"])
    assert client.get("/invoices/nope").status_code == 404


def test_audit_endpoint_ordered_events(api_db):
    _upload("d1_normal")
    rep = client.get("/invoices/d1_normal/audit").json()
    stages = [e["stage"] for e in rep["events"]]
    assert stages[:5] == ["received", "extracted", "validated", "matched", "policy_decided"]
    assert rep["events"][-1]["stage"] == "in_review"
    assert all(e["timestamp"] for e in rep["events"])


def test_document_endpoint_serves_pdf(api_db):
    _upload("d9_small")
    r = client.get("/invoices/d9_small/document")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_review_approve_resolves_exception(api_db):
    _upload("d2_qty_mismatch")
    r = client.post("/invoices/d2_qty_mismatch/review",
                    json={"reviewer": "yuki", "action": "approve", "comments": "verified with vendor"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    with db.get_conn() as conn:
        ex = conn.execute("SELECT status FROM exceptions WHERE invoice_id='d2_qty_mismatch'").fetchone()
        ra = conn.execute("SELECT reviewer, action FROM review_actions"
                          " WHERE invoice_id='d2_qty_mismatch'").fetchone()
    assert ex["status"] == "resolved" and ra["action"] == "approve"


def test_review_correct_resubmits(api_db):
    _upload("d2_qty_mismatch")  # invoiced 150 vs PO 100 on Product A → EXCEPTION (R004)
    # restore the exact PO (matcher checks exact qty + exact PO total): both lines
    r = client.post("/invoices/d2_qty_mismatch/review", json={
        "reviewer": "yuki", "action": "correct",
        "corrections": {"total_amount": 850000, "subtotal": 850000,
                        "line_items": [
                            {"description": "Product A", "quantity": 100, "unit_price": 1000, "amount": 100000},
                            {"description": "Product B", "quantity": 150, "unit_price": 5000, "amount": 750000}]}})
    body = r.json()
    assert r.status_code == 200
    # mismatches gone; re-decided on the corrected data → manager band (¥850k ≥ ¥100k)
    assert body["status"] == "in_review"
    d = client.get("/invoices/d2_qty_mismatch").json()
    assert d["decision"] == "MANAGER_REVIEW" and d["rule_id"] == "R007-manager-limit"


def test_review_unknown_invoice_404_and_bad_action_422(api_db):
    assert client.post("/invoices/nope/review",
                       json={"reviewer": "y", "action": "approve"}).status_code == 404
    assert client.post("/invoices/nope/review",
                       json={"reviewer": "y", "action": "teleport"}).status_code == 422


def test_exceptions_queue_open_only(api_db):
    _upload("d2_qty_mismatch")
    _upload("d9_small")  # clean — must not appear
    q = client.get("/exceptions").json()
    assert [e["invoice_id"] for e in q] == ["d2_qty_mismatch"]
    assert q[0]["severity"] == "high" and q[0]["total"]