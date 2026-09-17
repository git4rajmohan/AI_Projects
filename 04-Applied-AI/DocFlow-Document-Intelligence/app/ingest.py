"""Phase 3 — Document ingestion & text layer.

PyMuPDF text read + quality flag + OCR fallback (Phase 14): pages with little
or no text layer are rasterized and run through Tesseract. Degraded scans are
simulated (see tools/make_sample_invoices.py), detection is char-count + noise.
"""
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.config import settings
from app.extraction.ingest_error import IngestError

MIN_CHARS = 200  # ponytail: below this the read is suspect; tune per template later


@dataclass
class DocumentText:
    path: str
    text: str
    pages: int
    chars: int
    quality: str  # ok | poor
    ocr_used: bool = False  # True if any page came back from OCR


def _normalize(pages_text: list[str]) -> list[str]:
    # ponytail: header/footer = line repeated on every page of multi-page docs;
    # per-template rules if real-world chrome slips through
    if len(pages_text) > 1:
        top = [p.splitlines()[0] for p in pages_text if p.strip()]
        bottom = [p.splitlines()[-1] for p in pages_text if p.strip()]
        for line in set(top) | set(bottom):
            if top.count(line) == len(pages_text) and line.strip():
                pages_text = ["\n".join(l for l in p.splitlines() if l != line)
                              for p in pages_text]
    return pages_text


TESSERACT_CANDIDATES = (
    # ponytail: UB-Mannheim winget installer doesn't always update PATH; probe
    # standard dirs before giving up — drop when a proper PATH entry exists
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _ocr_available() -> bool:
    """pytesseract + a tesseract binary, without making them hard requirements."""
    try:
        import pytesseract
    except ImportError:
        return False
    try:
        _ensure_cmd(pytesseract)
        return bool(pytesseract.get_tesseract_version())  # binary reachable?
    except Exception:  # no binary / bad install → OCR silently off, text layer wins
        return False


def _ensure_cmd(pytesseract) -> None:
    """Point pytesseract at the engine: explicit setting > PATH > standard dirs."""
    import os

    if settings.tessdata_dir:  # explicit override wins
        pytesseract.pytesseract.tesseract_cmd = settings.tessdata_dir
        return
    for cand in TESSERACT_CANDIDATES:
        if os.path.isfile(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            return


def _ocr_page(page: "fitz.Page") -> str:
    import io

    import pytesseract
    from PIL import Image

    _ensure_cmd(pytesseract)
    pix = page.get_pixmap(dpi=200)  # ponytail: 200dpi plain text; 300 if blurry scans arrive
    png = pix.tobytes("png")
    return pytesseract.image_to_string(Image.open(io.BytesIO(png)))


def load_document(path: str | Path) -> DocumentText:
    path = Path(path)
    ocr_used = False
    try:
        doc = fitz.open(path)
        n_pages = doc.page_count
        pages: list[str] = []
        for page in doc:
            text_layer = "" if settings.ocr_mode == "only" else page.get_text()
            needs_ocr = settings.ocr_mode == "only" or (
                settings.ocr_mode == "auto" and len(text_layer.strip()) < MIN_CHARS)
            if needs_ocr and _ocr_available():
                text_layer = _ocr_page(page)  # ocr "off"/no-binary: keep text layer as-is
                ocr_used = True
            pages.append(text_layer)
        doc.close()
    except Exception as e:  # corrupt/encrypted/non-PDF bytes — fitz raises several types
        raise IngestError(f"unreadable document {path.name}: {e}") from e
    pages = _normalize(pages)
    text = "\n".join(pages).strip()
    # Degraded scan: generator garbles ~6/7 chars into non-ASCII noise
    noise = sum(1 for c in text if not c.isascii() and not c.isspace())
    printable = len(text)
    poor = printable < MIN_CHARS or (printable and noise / printable > 0.3)
    return DocumentText(path=str(path), text=text, pages=n_pages,
                        chars=printable, quality="poor" if poor else "ok",
                        ocr_used=ocr_used)