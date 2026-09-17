import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.ingest import _ocr_available, load_document

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "invoices"


def test_normal_pdf_yields_text():
    d = load_document(SAMPLES / "d1_normal.pdf")
    assert d.quality == "ok" and d.pages == 1
    assert d.chars > 200
    assert "INV-10026" in d.text and "850,000" in d.text
    assert d.ocr_used is False  # born-digital pages never need OCR


def test_poor_quality_flagged():
    d = load_document(SAMPLES / "d6_low_confidence.pdf")
    assert d.quality == "poor"


def test_all_samples_ingest():
    for p in SAMPLES.glob("*.pdf"):
        d = load_document(p)
        # d10 on a Tesseract-less machine has zero text — that's the graceful path
        assert d.pages >= 1, p.name
        assert d.text or (p.stem == "d10_scanned" and not _ocr_available()), p.name


# ---------- Phase 14 — OCR fallback ----------

def test_image_only_scan_ingests_via_ocr(monkeypatch):
    """The one new behavior: a zero-text-layer page is OCR'd when Tesseract
    exists; when it doesn't, ingest still returns a DocumentText (poor quality,
    ocr_used=False) instead of raising — never a 500 on the upload route."""
    d = load_document(SAMPLES / "d10_scanned.pdf")
    from app.ingest import _ocr_available
    if _ocr_available():
        assert d.ocr_used is True
        assert d.text.strip(), "OCR must produce text on an image-only page"
        # ponytail: Tesseract's column detection splits labels from values, so
        # assert on a value ("850,000"), not on "INV-10034" as one string
        assert "850,000" in d.text
    else:  # no Tesseract on this machine: graceful degradation
        assert d.ocr_used is False
        assert d.quality == "poor"


def test_ocr_off_keeps_text_layer(monkeypatch):
    monkeypatch.setattr(settings, "ocr_mode", "off")
    d = load_document(SAMPLES / "d10_scanned.pdf")
    assert d.ocr_used is False
    assert d.text == ""  # no text layer, OCR off → nothing to read


def test_ocr_only_uses_ocr_path(monkeypatch):
    """ocr_mode='only' skips the text layer even on born-digital pages."""
    from app.ingest import _ocr_available
    monkeypatch.setattr(settings, "ocr_mode", "only")
    d = load_document(SAMPLES / "d1_normal.pdf")
    if _ocr_available():
        assert d.ocr_used is True
        assert "INVOICE" in d.text
    else:
        assert d.ocr_used is False