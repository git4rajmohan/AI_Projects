import pytest

import app.db as db


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "test.db")
    db.seed(p)
    return p


def test_init_db_idempotent(db_path):
    db.init_db(db_path)  # second run must not raise


def test_seed_vendors(db_path):
    v = db.get_vendor("V-10025", db_path)
    assert v["name"] == "ABC Supplier" and v["status"] == "active"
    assert db.get_vendor("V-10028", db_path)["status"] == "inactive"


def test_seed_po_with_lines(db_path):
    po = db.get_po("PO-12345", db_path)
    assert po["vendor_id"] == "V-10025" and po["currency"] == "JPY"
    total = sum(l["quantity"] * l["unit_price"] for l in po["lines"])
    assert total == 850_000
    assert db.get_po("PO-99999", db_path) is None


def test_receipts(db_path):
    receipts = db.get_receipts_for_po("PO-20005", db_path)
    assert receipts[0]["quantity_received"] == 80  # 3-way mismatch case


def test_duplicate_lookup(db_path):
    dup = db.find_duplicate_invoice("V-10025", "INV-10025", db_path)
    assert dup is not None and dup["status"] == "paid"
    assert db.find_duplicate_invoice("V-10025", "INV-XXXXX", db_path) is None


def test_audit_event(db_path):
    db.save_audit_event("inv1", "test_stage", {"ok": True}, db_path)
    with db.get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM audit_events WHERE invoice_id='inv1'").fetchone()
    assert row["stage"] == "test_stage"