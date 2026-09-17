"""Phase 4 — AI field extraction. AI interprets; code stays in charge of math.

EXTRACTION_MODE=mock → pre-baked ground-truth JSON keyed by document stem.
EXTRACTION_MODE=live → OpenAI-compatible chat to Ollama, temperature 0, JSON only.
"""
import json
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings
from app.ingest import DocumentText

CRITICAL_FIELDS = ("vendor_name", "vendor_id", "invoice_number", "invoice_date",
                   "po_number", "currency", "total_amount", "bank_account")
POOR_CAP = 0.5  # §4.3: degraded docs can never self-report high confidence

PROMPT = """Extract invoice fields from the document text below.
Return ONLY a JSON object (no markdown fences) with keys:
vendor_name, vendor_id, invoice_number, invoice_date (YYYY-MM-DD), po_number,
currency (ISO 4217), line_items (list of {{description, quantity, unit_price, amount}}),
subtotal, tax, total_amount, bank_account,
confidence: object mapping each extracted field name to a 0.0-1.0 self-assessed confidence.

DOCUMENT TEXT:
{text}
"""


class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    amount: float | None = None  # ponytail: recomputed in math_consistent when absent


class ExtractedInvoice(BaseModel):
    vendor_name: str | None = None
    vendor_id: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    po_number: str | None = None
    currency: str | None = None
    line_items: list[LineItem] = []
    subtotal: float | None = None
    tax: float = 0
    total_amount: float | None = None
    bank_account: str | None = None
    confidence: float = 0.0
    field_confidence: dict[str, float] = {}
    extraction_inconsistent: bool = False
    quality: str = "ok"  # copied from ingest; downstream reads it too


def math_consistent(inv: ExtractedInvoice) -> bool:
    """Deterministic sanity check (§5): recompute the extraction's own math."""
    lines_sum = sum((li.amount if li.amount is not None else li.quantity * li.unit_price)
                    for li in inv.line_items)
    if inv.line_items and inv.subtotal is not None and abs(inv.subtotal - lines_sum) > 0.01:
        return False
    base = inv.subtotal if inv.subtotal is not None else (lines_sum if inv.line_items else None)
    if inv.total_amount is not None and base is not None and abs(inv.total_amount - (base + inv.tax)) > 0.01:
        return False
    return True


def _parse_json(raw: str) -> dict:
    # ponytail: brace-slice covers fences/prose around the JSON; json_repair lib if it ever isn't enough
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    lo, hi = raw.find("{"), raw.rfind("}")
    if 0 <= lo < hi:
        return json.loads(raw[lo:hi + 1])
    raise ValueError(f"Unparseable extraction output: {raw[:200]!r}")


def _mock_payload(doc: DocumentText) -> dict:
    stem = Path(doc.path).stem
    gt_path = Path(doc.path).with_name(stem + "_ground_truth.json")
    if not gt_path.exists():  # uploaded copy of a shipped sample: truth lives in data/invoices/
        gt_path = Path("data/invoices") / (stem + "_ground_truth.json")
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    conf = {k: 0.95 for k in gt if k != "line_items"}
    return {**gt, "confidence": 0.95, "field_confidence": conf, "quality": doc.quality}


def _live_payload(doc: DocumentText) -> dict:
    client = OpenAI(base_url=settings.ollama_base_url, api_key=settings.ollama_api_key)
    resp = client.chat.completions.create(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": PROMPT.format(text=doc.text[:8000])}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content or "")


def extract_invoice(doc: DocumentText) -> ExtractedInvoice:
    payload = _mock_payload(doc) if settings.extraction_mode == "mock" else _live_payload(doc)
    inv = ExtractedInvoice(**payload)
    if doc.quality == "poor":
        for f in CRITICAL_FIELDS:
            inv.field_confidence[f] = min(inv.field_confidence.get(f, 0.0), POOR_CAP)
        inv.confidence = min(inv.confidence, POOR_CAP)
    inv.quality = doc.quality
    inv.extraction_inconsistent = not math_consistent(inv)
    return inv