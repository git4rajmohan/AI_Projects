from datetime import date

from app.extraction.extractor import ExtractedInvoice, LineItem
from app.validation.validators import (DUPLICATE, FAIL, HIGH_RISK, PASS, SKIP,
                                       WARN, ValidationReport, validate_invoice)

from app.db import seed

TODAY = date(2026, 9, 15)  # fixed: pure function, no clock in the rule
VENDOR = {"vendor_id": "V-10025", "name": "ABC Supplier", "status": "active", "bank_account": "XXXX1234"}
PO = {"po_number": "PO-12345", "vendor_id": "V-10025", "currency": "JPY", "status": "open",
      "lines": [{"line_id": 1, "description": "Product A", "quantity": 100, "unit_price": 1000, "tax_rate": 0},
                {"line_id": 2, "description": "Product B", "quantity": 150, "unit_price": 5000, "tax_rate": 0}]}


def invoice(**over) -> ExtractedInvoice:
    base = dict(vendor_name="ABC Supplier", vendor_id="V-10025", invoice_number="INV-10026",
                invoice_date="2026-09-10", po_number="PO-12345", currency="JPY",
                bank_account="XXXX1234",
                line_items=[LineItem(description="Product A", quantity=100, unit_price=1000, amount=100000),
                            LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)],
                subtotal=850000, tax=0, total_amount=850000, confidence=0.95)
    return ExtractedInvoice(**{**base, **over})


def status_of(r: ValidationReport, name: str) -> str:
    c = r.get(name)
    assert c is not None, f"check {name} missing"
    return c.status


def test_all_pass():
    r = validate_invoice(invoice(), VENDOR, PO, today=TODAY)
    assert r.ok
    for name in ("required_fields", "vendor_exists", "vendor_active", "vendor_name_match",
                 "bank_account", "arithmetic", "currency", "duplicate", "date_sanity"):
        assert status_of(r, name) == PASS, f"{name}: {r.get(name).detail}"


def test_missing_required_field():
    r = validate_invoice(invoice(total_amount=None), VENDOR, PO, today=TODAY)
    assert status_of(r, "required_fields") == FAIL and not r.ok


def test_inactive_vendor():
    r = validate_invoice(invoice(), {**VENDOR, "status": "inactive"}, PO, today=TODAY)
    assert status_of(r, "vendor_active") == FAIL


def test_new_vendor_fails_active():
    r = validate_invoice(invoice(), {**VENDOR, "status": "new"}, PO, today=TODAY)
    assert status_of(r, "vendor_active") == FAIL  # §10: new vendor needs extra verification


def test_unknown_vendor():
    r = validate_invoice(invoice(vendor_id="V-XXXXX"), None, PO, today=TODAY)
    assert status_of(r, "vendor_exists") == FAIL


def test_vendor_name_similarity_warn_only():
    r = validate_invoice(invoice(vendor_name="abc supplier co."), VENDOR, PO, today=TODAY)
    assert status_of(r, "vendor_name_match") == WARN and r.ok  # warn never blocks


def test_bank_account_mismatch_high_risk():
    r = validate_invoice(invoice(bank_account="XXXX9876"), VENDOR, PO, today=TODAY)
    assert status_of(r, "bank_account") == HIGH_RISK


def test_bank_account_missing_warns():
    r = validate_invoice(invoice(bank_account=None), VENDOR, PO, today=TODAY)
    assert status_of(r, "bank_account") == WARN


def test_tampered_line_amount():
    lines = [LineItem(description="Product A", quantity=100, unit_price=1000, amount=150000),
             LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)]
    r = validate_invoice(invoice(line_items=lines), VENDOR, PO, today=TODAY)
    assert status_of(r, "arithmetic") == FAIL
    assert "line 1" in r.get("arithmetic").detail


def test_tampered_total():
    # §5.4: LLM says 850000 but lines sum 900000
    r = validate_invoice(invoice(total_amount=850000, subtotal=900000), VENDOR, PO, today=TODAY)
    assert status_of(r, "arithmetic") == FAIL


def test_currency_mismatch():
    r = validate_invoice(invoice(currency="USD"), VENDOR, PO, today=TODAY)
    assert status_of(r, "currency") == FAIL


def test_currency_skipped_without_po():
    r = validate_invoice(invoice(po_number=None), VENDOR, None, today=TODAY)
    assert status_of(r, "currency") == SKIP


def test_duplicate_detected():
    r = validate_invoice(invoice(), VENDOR, PO,
                         duplicate={"invoice_id": "inv_seed_1", "status": "paid"}, today=TODAY)
    assert status_of(r, "duplicate") == DUPLICATE and not r.ok


def test_date_in_future():
    r = validate_invoice(invoice(invoice_date="2026-10-01"), VENDOR, PO, today=TODAY)
    assert status_of(r, "date_sanity") == FAIL


def test_very_old_invoice():
    r = validate_invoice(invoice(invoice_date="2025-01-01"), VENDOR, PO, today=TODAY)
    assert status_of(r, "date_sanity") == FAIL


def test_unparseable_date():
    r = validate_invoice(invoice(invoice_date="10/9/2026"), VENDOR, PO, today=TODAY)
    assert status_of(r, "date_sanity") == FAIL


def test_against_seeded_db(tmp_path):
    # wire-up check: real seed rows flow through the pure validator
    from app.db import find_duplicate_invoice, get_po, get_vendor
    p = str(tmp_path / "t.db")
    seed(p)
    inv = invoice()
    r = validate_invoice(inv, get_vendor(inv.vendor_id, p), get_po(inv.po_number, p),
                         duplicate=find_duplicate_invoice(inv.vendor_id, inv.invoice_number, p),
                         today=TODAY)
    assert r.ok


def test_report_serializable():
    r = validate_invoice(invoice(), VENDOR, PO, today=TODAY)
    import json
    assert json.dumps(r.to_list())  # JSON-serializable for audit/API use