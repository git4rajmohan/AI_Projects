import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.extraction.extractor import ExtractedInvoice, extract_invoice, math_consistent
from app.ingest import load_document

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "invoices"


def test_mock_extracts_ground_truth():
    inv = extract_invoice(load_document(SAMPLES / "d1_normal.pdf"))
    assert isinstance(inv, ExtractedInvoice)
    assert inv.invoice_number == "INV-10026"
    assert inv.total_amount == 850_000
    assert len(inv.line_items) == 2
    assert inv.confidence >= settings.confidence_floor
    assert not inv.extraction_inconsistent


def test_mock_poor_quality_caps_confidence():
    inv = extract_invoice(load_document(SAMPLES / "d6_low_confidence.pdf"))
    assert inv.field_confidence["total_amount"] <= 0.5
    assert inv.confidence < settings.confidence_floor


def test_mock_all_samples_valid_and_consistent():
    for gt_path in SAMPLES.glob("*_ground_truth.json"):
        pdf = gt_path.with_name(gt_path.name.replace("_ground_truth.json", ".pdf"))
        inv = extract_invoice(load_document(pdf))
        assert inv.invoice_number, pdf.name
        assert not inv.extraction_inconsistent, pdf.name


def test_sanity_guard_flags_tampered_math():
    inv = ExtractedInvoice(
        line_items=[{"description": "Product A", "quantity": 100, "unit_price": 1000, "amount": 100000}],
        subtotal=900_000, tax=0, total_amount=900_000)
    assert not math_consistent(inv)


DOCFLOW_LIVE = os.environ.get("DOCFLOW_LIVE")


@pytest.mark.skipif(not DOCFLOW_LIVE, reason="set DOCFLOW_LIVE=1 with Ollama reachable")
def test_live_extracts_normal_sample(monkeypatch):
    monkeypatch.setattr(settings, "extraction_mode", "live")
    gt = json.loads((SAMPLES / "d1_normal_ground_truth.json").read_text(encoding="utf-8"))
    inv = extract_invoice(load_document(SAMPLES / "d1_normal.pdf"))
    fields = ["vendor_name", "invoice_number", "invoice_date", "po_number", "currency", "total_amount"]
    hits = sum(getattr(inv, f) == gt[f] for f in fields)
    assert hits / len(fields) >= 0.9