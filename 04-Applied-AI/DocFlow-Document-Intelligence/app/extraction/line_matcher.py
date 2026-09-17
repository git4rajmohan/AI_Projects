"""Phase 6.2 — AI line-item mapping (§21): the LLM only PROPOSES which invoice
line maps to which PO line. Verification of qty/price happens in matcher.py.
Mock mode: exact-description matching — deterministic and good enough for the
sample suite (descriptions are exact there). Live mode: one Ollama call.
"""
import json

from openai import OpenAI

from app.config import settings
from app.extraction.extractor import ExtractedInvoice

PROMPT = """Given invoice line items and purchase order line items (JSON below),
return ONLY a JSON object mapping invoice line INDEX (0-based) to po line_id.
Only map lines that clearly refer to the same product/service. Omit unmapped lines.

INVOICE LINES: {inv}
PO LINES: {po}
"""


def _mock_map(inv: ExtractedInvoice, po: dict | None) -> dict[int, int]:
    # ponytail: casefold exact-match; difflib SequenceMatcher if fuzzy PO descriptions arrive
    if po is None:
        return {}
    by_desc = {l["description"].casefold(): l["line_id"] for l in po["lines"]}
    return {i: by_desc[li.description.casefold()]
            for i, li in enumerate(inv.line_items) if li.description.casefold() in by_desc}


def _live_map(inv: ExtractedInvoice, po: dict | None) -> dict[int, int]:
    if po is None:
        return {}
    client = OpenAI(base_url=settings.ollama_base_url, api_key=settings.ollama_api_key)
    resp = client.chat.completions.create(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": PROMPT.format(
            inv=json.dumps([li.model_dump() for li in inv.line_items]),
            po=json.dumps(po["lines"]))}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = json.loads(resp.choices[0].message.content or "{}")
    po_ids = {l["line_id"] for l in po["lines"]}
    # keep only integer keys with valid po line ids; anything malformed = unmapped
    return {int(k): int(v) for k, v in raw.items() if int(v) in po_ids and str(k).isdigit()}


def suggest_line_map(inv: ExtractedInvoice, po: dict | None) -> dict[int, int]:
    return _mock_map(inv, po) if settings.extraction_mode == "mock" else _live_map(inv, po)