from app.extraction.extractor import ExtractedInvoice, LineItem
from app.matching.matcher import (MISMATCH, MATCH, NOT_FOUND, SKIP, three_way_match,
                                  two_way_match)
from app.validation.validators import Check

PO = {"po_number": "PO-12345", "vendor_id": "V-10025", "currency": "JPY", "status": "open",
      "lines": [{"line_id": 1, "description": "Product A", "quantity": 100, "unit_price": 1000, "tax_rate": 0},
                {"line_id": 2, "description": "Product B", "quantity": 150, "unit_price": 5000, "tax_rate": 0}]}
RECEIPTS = [{"gr_number": "GR-30001", "po_number": "PO-12345", "line_id": 1, "quantity_received": 100},
            {"gr_number": "GR-30002", "po_number": "PO-12345", "line_id": 2, "quantity_received": 150}]


def invoice(**over) -> ExtractedInvoice:
    base = dict(vendor_name="ABC Supplier", vendor_id="V-10025", invoice_number="INV-10026",
                invoice_date="2026-09-10", po_number="PO-12345", currency="JPY",
                bank_account="XXXX1234",
                line_items=[LineItem(description="Product A", quantity=100, unit_price=1000, amount=100000),
                            LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)],
                subtotal=850000, tax=0, total_amount=850000, confidence=0.95)
    return ExtractedInvoice(**{**base, **over})


FULL_MAP = {0: 1, 1: 2}


def status_of(report, name):
    c = report.get(name)
    assert c is not None, f"check {name} missing"
    return c.status


def test_matching_invoice_po_all_match():
    r = two_way_match(invoice(), PO, FULL_MAP)
    assert r.ok
    for name in ("po_exists", "po_vendor", "line_mapping", "quantity", "unit_price", "total"):
        assert status_of(r, name) == MATCH, f"{name}: {r.get(name).detail}"
    assert r.line_map == FULL_MAP


def test_missing_po():
    r = two_way_match(invoice(po_number="PO-99999"), None, {})
    assert status_of(r, "po_exists") == NOT_FOUND and not r.ok


def test_qty_mismatch_150_vs_100():
    inv = invoice(line_items=[LineItem(description="Product A", quantity=150, unit_price=1000, amount=150000),
                              LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)],
                  subtotal=900000, total_amount=900000)
    r = two_way_match(inv, PO, FULL_MAP)
    assert status_of(r, "quantity") == MISMATCH
    assert "150" in r.get("quantity").detail and "100" in r.get("quantity").detail
    assert status_of(r, "total") == MISMATCH  # 900k != 850k PO total


def test_price_over_tolerance():
    inv = invoice(line_items=[LineItem(description="Product A", quantity=100, unit_price=1050, amount=105000),
                              LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)],
                  subtotal=855000, total_amount=855000)
    r = two_way_match(inv, PO, FULL_MAP)
    assert status_of(r, "unit_price") == MISMATCH  # 5% > 0.5% tolerance


def test_price_within_tolerance_passes():
    inv = invoice(line_items=[LineItem(description="Product A", quantity=100, unit_price=1004, amount=100400),
                              LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)],
                  subtotal=850400, total_amount=850400)
    r = two_way_match(inv, PO, FULL_MAP)
    assert status_of(r, "unit_price") == MATCH  # 0.4% <= 0.5%


def test_unmapped_line_flagged():
    inv = invoice(line_items=[LineItem(description="Mystery Widget", quantity=1, unit_price=999, amount=999)])
    r = two_way_match(inv, PO, {})
    assert status_of(r, "line_mapping") == MISMATCH


def test_wrong_vendor_for_po():
    r = two_way_match(invoice(vendor_id="V-10026"), PO, FULL_MAP)
    assert status_of(r, "po_vendor") == MISMATCH


def test_three_way_all_match():
    r = three_way_match(invoice(), PO, RECEIPTS, FULL_MAP)
    assert status_of(r, "goods_receipt") == MATCH


def test_three_way_invoiced_over_received():
    inv = invoice(line_items=[LineItem(description="Product A", quantity=100, unit_price=1000, amount=100000)])
    receipts = [{"gr_number": "GR-30001", "po_number": "PO-12345", "line_id": 1, "quantity_received": 80}]
    r = three_way_match(inv, PO, receipts, {0: 1})
    assert status_of(r, "goods_receipt") == MISMATCH
    assert "80" in r.get("goods_receipt").detail


def test_three_way_skips_without_receipts():
    assert status_of(three_way_match(invoice(), PO, [], FULL_MAP), "goods_receipt") == SKIP
    assert status_of(three_way_match(invoice(), None, RECEIPTS, FULL_MAP), "goods_receipt") == SKIP


def test_against_seeded_db(tmp_path):
    # wire-up: seed rows + mock line matcher flow through the pure matchers
    from app.db import get_po, get_receipts_for_po, seed
    from app.extraction.line_matcher import suggest_line_map
    p = str(tmp_path / "t.db")
    seed(p)
    inv = invoice()
    po = get_po(inv.po_number, p)
    m = suggest_line_map(inv, po)
    assert two_way_match(inv, po, m).ok
    assert three_way_match(inv, po, get_receipts_for_po(po["po_number"], p), m).ok


def test_report_serializable():
    import json
    assert json.dumps(two_way_match(invoice(), PO, FULL_MAP).to_list())