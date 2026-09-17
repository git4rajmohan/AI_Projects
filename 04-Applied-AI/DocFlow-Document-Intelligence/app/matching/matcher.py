"""Phase 6 — invoice <-> PO (two-way, §8) and PO <-> receipt <-> invoice (three-way, §9).

Pure functions: (extracted, po, receipts, line_map) -> MatchReport. The AI only
PROPOSES the line mapping (app/extraction/line_matcher.py); this code verifies
quantities, prices, and totals and owns every verdict. No LLM here.
"""
from dataclasses import asdict, dataclass, field

from app.config import settings
from app.extraction.extractor import ExtractedInvoice
from app.validation.validators import Check

MATCH, MISMATCH, NOT_FOUND, SKIP = "MATCH", "MISMATCH", "NOT_FOUND", "SKIP"


@dataclass
class MatchReport:
    checks: list[Check]
    line_map: dict[int, int] = field(default_factory=dict)  # invoice line idx -> PO line_id

    def get(self, name: str) -> Check | None:
        return next((c for c in self.checks if c.name == name), None)

    @property
    def ok(self) -> bool:
        return all(c.status in (MATCH, SKIP) for c in self.checks)

    def to_list(self) -> list[dict]:
        return [asdict(c) for c in self.checks]


def two_way_match(inv: ExtractedInvoice, po: dict | None,
                  line_map: dict[int, int]) -> MatchReport:
    if po is None:
        return MatchReport([Check("po_exists", NOT_FOUND, f"PO {inv.po_number!r} not found")])
    checks = [
        Check("po_exists", MATCH, f"{po['po_number']} ({po['status']})"),
        Check("po_vendor", MATCH if inv.vendor_id == po["vendor_id"] else MISMATCH,
              f"invoice {inv.vendor_id} vs PO {po['vendor_id']}"),
    ]
    po_lines = {l["line_id"]: l for l in po["lines"]}
    unmapped = [f"line {i + 1} ({li.description!r})"
                for i, li in enumerate(inv.line_items) if line_map.get(i) not in po_lines]
    checks.append(Check("line_mapping", MISMATCH if unmapped else MATCH,
                        "; ".join(unmapped) or f"{len(line_map)} line(s) mapped"))
    qty_bad, price_bad = [], []
    for i, li in enumerate(inv.line_items):
        po_line = po_lines.get(line_map.get(i))
        if po_line is None:
            continue
        if abs(li.quantity - po_line["quantity"]) > settings.qty_tolerance:
            qty_bad.append(f"{li.description}: invoiced {li.quantity:g} vs PO {po_line['quantity']:g}")
        allowed = settings.price_tolerance_pct / 100 * po_line["unit_price"]
        if abs(li.unit_price - po_line["unit_price"]) > allowed:
            price_bad.append(f"{li.description}: invoiced {li.unit_price:g} vs PO {po_line['unit_price']:g}")
    checks.append(Check("quantity", MISMATCH if qty_bad else MATCH, "; ".join(qty_bad) or "within tolerance"))
    checks.append(Check("unit_price", MISMATCH if price_bad else MATCH,
                        "; ".join(price_bad) or "within tolerance"))
    # ponytail: exact PO total (no partial invoicing); support partials when a real AP flow needs them
    po_total = sum(l["quantity"] * l["unit_price"] for l in po["lines"])
    total = inv.total_amount or 0
    checks.append(Check("total", MATCH if abs(total - po_total) < 0.01 else MISMATCH,
                        f"invoice {total:g} vs PO {po_total:g}"))
    return MatchReport(checks, line_map)


def three_way_match(inv: ExtractedInvoice, po: dict | None,
                    receipts: list[dict], line_map: dict[int, int]) -> MatchReport:
    if po is None:
        return MatchReport([Check("goods_receipt", SKIP, "no PO — two-way already flagged")])
    if not receipts:
        return MatchReport([Check("goods_receipt", SKIP, "no goods receipts recorded for this PO")])
    received: dict[int, float] = {}
    for r in receipts:
        if r["line_id"] is not None:
            received[r["line_id"]] = received.get(r["line_id"], 0) + r["quantity_received"]
    po_lines = {l["line_id"]: l for l in po["lines"]}
    # ponytail: lines with no receipt at all are skipped here; strict GR-first policy if the business wants it
    problems = []
    for i, li in enumerate(inv.line_items):
        lid = line_map.get(i)
        if lid not in po_lines or lid not in received:
            continue
        rec = received[lid]
        if li.quantity > rec + settings.qty_tolerance:
            problems.append(f"{li.description}: invoiced {li.quantity:g} > received {rec:g}")
    return MatchReport([Check("goods_receipt", MISMATCH if problems else MATCH,
                              "; ".join(problems) or "invoiced quantities covered by receipts")],
                       line_map)