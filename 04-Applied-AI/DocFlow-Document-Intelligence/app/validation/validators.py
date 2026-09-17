"""Phase 5 — deterministic validation (§5, §6, §11). Pure functions:
(extracted fields, DB records) -> ValidationReport. No LLM, no I/O.
"""
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from app.config import settings
from app.extraction.extractor import ExtractedInvoice

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
HIGH_RISK, DUPLICATE, SKIP = "HIGH_RISK", "DUPLICATE", "SKIP"
REQUIRED = ("vendor_name", "invoice_number", "invoice_date", "po_number", "currency", "total_amount")


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class ValidationReport:
    checks: list[Check]

    def get(self, name: str) -> Check | None:
        return next((c for c in self.checks if c.name == name), None)

    @property
    def ok(self) -> bool:
        """True when nothing blocks auto-processing (warnings don't block)."""
        return all(c.status in (PASS, WARN, SKIP) for c in self.checks)

    def to_list(self) -> list[dict]:
        return [asdict(c) for c in self.checks]


def _norm(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


def _required(inv: ExtractedInvoice) -> Check:
    missing = [f for f in REQUIRED if getattr(inv, f) is None]
    return Check("required_fields", FAIL if missing else PASS,
                 f"missing: {', '.join(missing)}" if missing else "all present")


def _vendor_checks(inv: ExtractedInvoice, vendor: dict | None) -> list[Check]:
    if vendor is None:
        return [Check("vendor_exists", FAIL, f"vendor_id {inv.vendor_id!r} not in vendor master")]
    checks = [Check("vendor_exists", PASS, f"{vendor['vendor_id']} ({vendor['status']})"),
              Check("vendor_active", PASS if vendor["status"] == "active" else FAIL,
                    f"vendor status is {vendor['status']}")]
    if _norm(inv.vendor_name) == _norm(vendor["name"]):
        checks.append(Check("vendor_name_match", PASS, vendor["name"]))
    else:  # similarity, not equality — human judges, code only warns
        checks.append(Check("vendor_name_match", WARN,
                            f"invoice {inv.vendor_name!r} vs master {vendor['name']!r}"))
    if not inv.bank_account:
        checks.append(Check("bank_account", WARN, "no bank account on invoice"))
    # ponytail: exact compare on last-4-style ids; normalize digits if real IBANs arrive
    elif inv.bank_account != vendor["bank_account"]:
        checks.append(Check("bank_account", HIGH_RISK,
                            f"invoice {inv.bank_account} vs master {vendor['bank_account']}"))
    else:
        checks.append(Check("bank_account", PASS, vendor["bank_account"]))
    return checks


def _arithmetic(inv: ExtractedInvoice) -> Check:
    problems = []
    for i, li in enumerate(inv.line_items, 1):
        if li.amount is not None and abs(li.amount - li.quantity * li.unit_price) > 0.01:
            problems.append(f"line {i}: {li.amount} != {li.quantity}x{li.unit_price}")
    lines_sum = sum(li.amount if li.amount is not None else li.quantity * li.unit_price
                    for li in inv.line_items)
    if inv.line_items and inv.subtotal is not None and abs(inv.subtotal - lines_sum) > 0.01:
        problems.append(f"subtotal {inv.subtotal} != sum(lines) {lines_sum:g}")
    base = inv.subtotal if inv.subtotal is not None else (lines_sum if inv.line_items else None)
    if inv.total_amount is not None and base is not None and abs(inv.total_amount - (base + inv.tax)) > 0.01:
        problems.append(f"total {inv.total_amount:g} != subtotal {base:g} + tax {inv.tax:g}")
    return Check("arithmetic", FAIL if problems else PASS, "; ".join(problems) or "recomputed ok")


def _currency(inv: ExtractedInvoice, po: dict | None) -> Check:
    if po is None:
        return Check("currency", SKIP, "no PO to compare")
    if (inv.currency or "") != po["currency"]:
        return Check("currency", FAIL, f"invoice {inv.currency} vs PO {po['currency']}")
    return Check("currency", PASS, str(inv.currency))


def _duplicate(inv: ExtractedInvoice, dup: dict | None) -> Check:
    if dup is None:
        return Check("duplicate", PASS, "no prior invoice for this vendor+number")
    return Check("duplicate", DUPLICATE,
                 f"duplicate of {dup['invoice_id']} (status {dup['status']})")


def _date_sanity(inv: ExtractedInvoice, today: date) -> Check:
    try:
        d = date.fromisoformat(inv.invoice_date or "")
    except ValueError:
        return Check("date_sanity", FAIL, f"unparseable invoice_date {inv.invoice_date!r}")
    if d > today:
        return Check("date_sanity", FAIL, f"invoice dated in the future ({d})")
    if d < today - timedelta(days=settings.max_invoice_age_days):
        return Check("date_sanity", FAIL,
                     f"invoice older than {settings.max_invoice_age_days} days ({d})")
    return Check("date_sanity", PASS, str(d))


def validate_invoice(inv: ExtractedInvoice, vendor: dict | None, po: dict | None,
                     duplicate: dict | None = None,
                     today: date | None = None) -> ValidationReport:
    """Pure: caller fetches vendor/po/duplicate rows; this only compares."""
    checks = [_required(inv), *_vendor_checks(inv, vendor), _arithmetic(inv),
              _currency(inv, po), _duplicate(inv, duplicate),
              _date_sanity(inv, today or date.today())]
    return ValidationReport(checks)