import json
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "invoices"


@pytest.fixture(scope="module", autouse=True)
def generated():
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_invoices.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_all_pdfs_exist():
    for name in ["d1_normal", "d2_qty_mismatch", "d3_duplicate", "d4_bank_change",
                 "d5_missing_po", "d6_low_confidence", "d7_high_value", "d8_currency_mismatch",
                 "d9_small"]:
        assert (SAMPLES / f"{name}.pdf").exists(), name
        assert (SAMPLES / f"{name}_ground_truth.json").exists(), name


def test_pdfs_open_and_have_text():
    doc = fitz.open(SAMPLES / "d1_normal.pdf")
    text = doc[0].get_text()
    doc.close()
    assert "INV-10026" in text and "850,000" in text


def test_ground_truth_parses_and_totals_match():
    gt = json.loads((SAMPLES / "d1_normal_ground_truth.json").read_text(encoding="utf-8"))
    assert gt["total_amount"] == 850_000
    lines_sum = sum(l["amount"] for l in gt["line_items"])
    assert gt["subtotal"] == lines_sum == 850_000


def test_degraded_sample_is_garbled():
    doc = fitz.open(SAMPLES / "d6_low_confidence.pdf")
    text = doc[0].get_text()
    doc.close()
    # garbled → mostly noise chars, original invoice number not directly present
    assert "·" in text
    assert text.count("·") > len(text) // 2