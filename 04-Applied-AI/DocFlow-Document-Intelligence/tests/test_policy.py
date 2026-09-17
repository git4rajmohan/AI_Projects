import json

from app.extraction.extractor import ExtractedInvoice, LineItem
from app.matching.matcher import NOT_FOUND, three_way_match, two_way_match
from app.policy.engine import (AUTO_APPROVE, EXCEPTION, FINANCE_REVIEW, HUMAN_REVIEW,
                               MANAGER_REVIEW, REJECT, decide)
from app.validation.validators import validate_invoice

PO = {"po_number": "PO-12345", "vendor_id": "V-10025", "currency": "JPY", "status": "open",
      "lines": [{"line_id": 1, "description": "Product A", "quantity": 100, "unit_price": 1000, "tax_rate": 0},
                {"line_id": 2, "description": "Product B", "quantity": 150, "unit_price": 5000, "tax_rate": 0}]}
VENDOR = {"vendor_id": "V-10025", "name": "ABC Supplier", "status": "active", "bank_account": "XXXX1234"}
RECEIPTS = [{"gr_number": "GR-30001", "po_number": "PO-12345", "line_id": 1, "quantity_received": 100},
            {"gr_number": "GR-30002", "po_number": "PO-12345", "line_id": 2, "quantity_received": 150}]
FULL_MAP = {0: 1, 1: 2}
TODAY = __import__("datetime").date(2026, 9, 15)


def invoice(**over) -> ExtractedInvoice:
    base = dict(vendor_name="ABC Supplier", vendor_id="V-10025", invoice_number="INV-10026",
                invoice_date="2026-09-10", po_number="PO-12345", currency="JPY",
                bank_account="XXXX1234",
                line_items=[LineItem(description="Product A", quantity=100, unit_price=1000, amount=100000),
                            LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)],
                subtotal=850000, tax=0, total_amount=850000, confidence=0.95,
                field_confidence={f: 0.95 for f in
                                  ("vendor_name", "vendor_id", "invoice_number", "invoice_date",
                                   "po_number", "currency", "total_amount", "bank_account")})
    return ExtractedInvoice(**{**base, **over})


def run(inv, v_over=None, m_po=PO, receipts=None):
    v = validate_invoice(inv, VENDOR, m_po, duplicate=v_over, today=TODAY)
    m = two_way_match(inv, m_po, FULL_MAP)
    if receipts is not None:
        m = three_way_match(inv, m_po, receipts, FULL_MAP)
    return decide(v, m, inv)


def test_normal_small_invoice_auto_approves():
    small_po = {"po_number": "PO-30001", "vendor_id": "V-10025", "currency": "JPY", "status": "open",
                "lines": [{"line_id": 10, "description": "Product A", "quantity": 50, "unit_price": 1000, "tax_rate": 0}]}
    small = invoice(po_number="PO-30001", total_amount=50000, subtotal=50000,
                    line_items=[LineItem(description="Product A", quantity=50, unit_price=1000, amount=50000)])
    v = validate_invoice(small, VENDOR, small_po, today=TODAY)
    m = two_way_match(small, small_po, {0: 10})
    d = decide(v, m, small)
    assert d.decision == AUTO_APPROVE and d.rule_id == "R008-auto-approve"
    assert d.reasons[0].text.startswith("all checks passed")


def test_manager_review_band():
    d = run(invoice())  # 850,000 JPY
    assert d.decision == MANAGER_REVIEW and d.rule_id == "R007-manager-limit"


def test_finance_band_blocked_by_missing_po():
    # total 1.2M > manager_limit, but missing PO outranks the threshold band (§7 priority)
    inv = invoice(total_amount=1_200_000, subtotal=1_200_000, po_number="PO-99999",
                  line_items=[LineItem(description="Product A", quantity=4, unit_price=300000, amount=1200000)])
    d = run(inv, m_po=None)
    assert d.decision == EXCEPTION  # missing PO outranks threshold band


def test_finance_band_with_clean_match():
    # clean PO-20003 (4 x 300,000 = 1.2M)
    po = {"po_number": "PO-20003", "vendor_id": "V-10025", "currency": "JPY", "status": "open",
          "lines": [{"line_id": 5, "description": "Service X", "quantity": 4, "unit_price": 300000, "tax_rate": 0}]}
    inv = invoice(po_number="PO-20003", total_amount=1_200_000, subtotal=1_200_000,
                  line_items=[LineItem(description="Service X", quantity=4, unit_price=300000, amount=1200000)])
    v = validate_invoice(inv, VENDOR, po, today=TODAY)
    m = two_way_match(inv, po, {0: 5})
    d = decide(v, m, inv)
    assert d.decision == FINANCE_REVIEW and d.rule_id == "R006-finance-limit"


def test_duplicate_beats_everything():
    d = run(invoice(), v_over={"invoice_id": "inv_seed_1", "status": "paid"})
    assert d.decision == REJECT and d.rule_id == "R001-duplicate"
    # never auto-approved even though other rules also fire
    assert all(r.rule_id != "R008-auto-approve" for r in d.reasons)


def test_high_value_plus_duplicate_duplicate_wins():
    inv = invoice(po_number="PO-20003", total_amount=1_200_000, subtotal=1_200_000,
                  line_items=[LineItem(description="Service X", quantity=4, unit_price=300000, amount=1200000)])
    d = run(inv, v_over={"invoice_id": "x", "status": "paid"})
    assert d.decision == REJECT


def test_bank_change_human_review():
    d = run(invoice(bank_account="XXXX9876"))
    assert d.decision == HUMAN_REVIEW and d.rule_id == "R002-bank-change"


def test_missing_po_exception():
    inv = invoice(po_number="PO-99999")
    d = run(inv, m_po=None)
    assert d.decision == EXCEPTION and d.rule_id == "R003-missing-po"


def test_qty_mismatch_exception():
    inv = invoice(line_items=[LineItem(description="Product A", quantity=150, unit_price=1000, amount=150000),
                              LineItem(description="Product B", quantity=150, unit_price=5000, amount=750000)],
                  subtotal=900000, total_amount=900000)
    d = run(inv)
    assert d.decision == EXCEPTION and d.rule_id == "R004-mismatch"


def test_low_confidence_human_review():
    inv = invoice()
    inv.field_confidence = {f: 0.95 for f in inv.field_confidence}
    inv.field_confidence["total_amount"] = 0.42
    d = run(inv)
    assert d.decision == HUMAN_REVIEW and d.rule_id == "R005-low-confidence"
    assert "total_amount" in d.reasons[0].text


def test_bank_change_outranks_low_confidence():
    inv = invoice(bank_account="XXXX9876")
    inv.field_confidence["total_amount"] = 0.3
    d = run(inv)
    assert d.decision == HUMAN_REVIEW and d.rule_id == "R002-bank-change"


def test_missing_po_outranks_mismatch():
    inv = invoice(po_number="PO-99999", currency="USD")
    d = run(inv, m_po=None)
    assert d.decision == EXCEPTION and d.rule_id == "R003-missing-po"


def test_all_triggered_rules_listed():
    # duplicate + bank change + low confidence all fire; reasons[] carries all three
    inv = invoice(bank_account="XXXX9876")
    inv.field_confidence["total_amount"] = 0.1
    d = run(inv, v_over={"invoice_id": "x", "status": "paid"})
    ids = [r.rule_id for r in d.reasons]
    assert ids[:3] == ["R001-duplicate", "R002-bank-change", "R005-low-confidence"]
    # threshold rule always evaluated last; 850k lands in the manager band
    assert d.reasons[-1].rule_id == "R007-manager-limit"


def test_decision_serializable():
    d = run(invoice())
    assert json.dumps(d.to_dict())


def test_no_llm_import():
    # §7.3: policy module must not import openai/LLM anywhere
    import app.policy.engine as eng
    assert "openai" not in eng.__file__ and not hasattr(eng, "OpenAI")