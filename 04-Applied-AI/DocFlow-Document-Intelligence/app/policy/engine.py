"""Phase 7 — deterministic approval policy (§10). Pure function of
(ValidationReport, MatchReport, ExtractedInvoice). No LLM, no I/O.

Priority (first trigger wins): duplicate > bank-change > missing-PO >
mismatch > low-confidence > amount threshold. Every triggered rule lands
in reasons[] for §13 explainability.
"""
from dataclasses import asdict, dataclass

from app.config import settings
from app.extraction.extractor import CRITICAL_FIELDS, ExtractedInvoice
from app.matching.matcher import MISMATCH, NOT_FOUND, MatchReport
from app.validation.validators import DUPLICATE, FAIL, HIGH_RISK, ValidationReport

AUTO_APPROVE = "AUTO_APPROVE"
MANAGER_REVIEW = "MANAGER_REVIEW"
FINANCE_REVIEW = "FINANCE_REVIEW"
REJECT = "REJECT"
HUMAN_REVIEW = "HUMAN_REVIEW"
EXCEPTION = "EXCEPTION"


@dataclass
class Reason:
    rule_id: str
    text: str


@dataclass
class PolicyDecision:
    decision: str
    rule_id: str
    reasons: list[Reason]

    def to_dict(self) -> dict:
        return asdict(self)


def _st(report, name: str) -> tuple[str | None, str]:
    c = report.get(name)
    return (c.status, c.detail) if c else (None, "")


def decide(v: ValidationReport, m: MatchReport, inv: ExtractedInvoice) -> PolicyDecision:
    """Ordered rules; every triggered rule lands in reasons (§13)."""
    total = inv.total_amount or 0
    low = [f for f in CRITICAL_FIELDS
           if inv.field_confidence.get(f, 0.0) < settings.confidence_floor]
    rules: list[tuple[str, str, str]] = []  # (rule_id, decision, human-readable reason)

    st, det = _st(v, "duplicate")
    if st == DUPLICATE:
        rules.append(("R001-duplicate", REJECT, f"duplicate invoice — {det}"))

    st, det = _st(v, "bank_account")
    if st == HIGH_RISK:
        rules.append(("R002-bank-change", HUMAN_REVIEW, f"bank account changed — {det}"))

    st, _ = _st(m, "po_exists")
    if st == NOT_FOUND:
        rules.append(("R003-missing-po", EXCEPTION, f"PO {inv.po_number} not found in PO system"))

    bad = [f"{c.name}: {c.detail}" for c in [*v.checks, *m.checks] if c.status in (FAIL, MISMATCH)]
    if bad:
        rules.append(("R004-mismatch", EXCEPTION, "; ".join(bad)))

    if low:
        rules.append(("R005-low-confidence", HUMAN_REVIEW,
                      f"extraction confidence < {settings.confidence_floor} for: {', '.join(low)}"))

    if total > settings.manager_limit:
        rules.append(("R006-finance-limit", FINANCE_REVIEW,
                      f"total {total:,.0f} > {settings.manager_limit:,} — finance approval required"))
    elif total >= settings.auto_approve_limit:
        rules.append(("R007-manager-limit", MANAGER_REVIEW,
                      f"total {total:,.0f} >= {settings.auto_approve_limit:,} — manager approval required"))
    else:
        rules.append(("R008-auto-approve", AUTO_APPROVE,
                      f"all checks passed; total {total:,.0f} < {settings.auto_approve_limit:,}"))

    rule_id, decision, _ = rules[0]
    return PolicyDecision(decision, rule_id, [Reason(rid, text) for rid, _, text in rules])