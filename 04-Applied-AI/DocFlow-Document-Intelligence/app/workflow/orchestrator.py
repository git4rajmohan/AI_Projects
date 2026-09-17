"""Phase 8 — workflow orchestrator (§ state machine + §12 reviewer actions).

process_invoice(): ingest → extract → validate → match → policy, persisting each
stage as a status transition + an audit event (stage name == status, which Phase 9's
reconstruction reads back in order). Reviewer actions re-enter from validation.
"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import app.db as db
from app.extraction.extractor import ExtractedInvoice, extract_invoice
from app.extraction.line_matcher import suggest_line_map
from app.ingest import DocumentText, load_document
from app.matching.matcher import MatchReport, three_way_match, two_way_match
from app.policy.engine import AUTO_APPROVE, EXCEPTION, REJECT, PolicyDecision, decide
from app.validation.validators import HIGH_RISK, ValidationReport, validate_invoice

# Invoice statuses (invoices.status). "policy_decided" never lands in the status
# column: the decision gets its own audit event, then the status jumps to its outcome.
RECEIVED, EXTRACTED, VALIDATED, MATCHED = "received", "extracted", "validated", "matched"
AUTO_APPROVED, IN_REVIEW, REJECTED = "auto_approved", "in_review", "rejected"
APPROVED, INFO_REQUESTED = "approved", "info_requested"
STATES = (RECEIVED, EXTRACTED, VALIDATED, MATCHED, "policy_decided",
          AUTO_APPROVED, IN_REVIEW, REJECTED, APPROVED, INFO_REQUESTED)

# policy decision -> parked status; every review-flavoured decision parks in_review
_PARK = {AUTO_APPROVE: AUTO_APPROVED, REJECT: REJECTED}
_ACTIONS = {"approve": APPROVED, "reject": REJECTED, "request_info": INFO_REQUESTED}


@dataclass
class WorkflowResult:
    invoice_id: str
    status: str
    decision: PolicyDecision
    validation: ValidationReport
    match: MatchReport
    extracted: ExtractedInvoice


def _stage(iid: str, status: str, payload: dict, db_path: str | None) -> None:
    """One pipeline step = one status transition + one audit event."""
    with db.get_conn(db_path) as conn:
        conn.execute("UPDATE invoices SET status=? WHERE invoice_id=?", (status, iid))
    db.save_audit_event(iid, status, payload, db_path)


def _insert_invoice(iid: str, inv: ExtractedInvoice, doc: DocumentText,
                    db_path: str | None) -> None:
    with db.get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO invoices (invoice_id, invoice_number, vendor_id, invoice_date, po_number,"
            " currency, subtotal, tax, total, bank_account, document_path, status, extracted_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, inv.invoice_number, inv.vendor_id, inv.invoice_date, inv.po_number,
             inv.currency, inv.subtotal or 0, inv.tax, inv.total_amount or 0,
             inv.bank_account, doc.path, RECEIVED, inv.model_dump_json()))
        for i, li in enumerate(inv.line_items, 1):
            conn.execute("INSERT INTO invoice_line_items VALUES (?,?,?,?,?,?)",
                         (iid, i, li.description, li.quantity, li.unit_price,
                          li.amount if li.amount is not None else li.quantity * li.unit_price))


def _maybe_exception(iid: str, v: ValidationReport, m: MatchReport, dec: PolicyDecision,
                     db_path: str | None) -> None:
    """8.3: exception rows only for policy EXCEPTION or a HIGH_RISK check."""
    hr = next((c for c in [*v.checks, *m.checks] if c.status == HIGH_RISK), None)
    if dec.decision == EXCEPTION:
        typ, reason = "policy_exception", "; ".join(r.text for r in dec.reasons)
    elif hr is not None:
        typ, reason = "high_risk", hr.detail
    else:
        return
    with db.get_conn(db_path) as conn:
        conn.execute("INSERT INTO exceptions (invoice_id, type, severity, reason) VALUES (?,?,?,?)",
                     (iid, typ, "high", reason))


def _resolve_exceptions(iid: str, db_path: str | None) -> None:
    with db.get_conn(db_path) as conn:
        conn.execute("UPDATE exceptions SET status='resolved' WHERE invoice_id=? AND status='open'",
                     (iid,))


def _run_pipeline(iid: str, inv: ExtractedInvoice, today: date | None,
                  db_path: str | None) -> WorkflowResult:
    """Validation → matching → policy for a stored invoice (re-entry point, 8.5)."""
    vendor = db.get_vendor(inv.vendor_id or "", db_path)
    po = db.get_po(inv.po_number or "", db_path)
    dup = db.find_duplicate_invoice(inv.vendor_id or "", inv.invoice_number or "", db_path)
    if dup is not None and dup["invoice_id"] == iid:
        dup = None  # re-entry after correction: its own stored row isn't a duplicate
    v = validate_invoice(inv, vendor, po, dup, today)
    _stage(iid, VALIDATED, {"checks": v.to_list()}, db_path)
    line_map = suggest_line_map(inv, po)
    m = two_way_match(inv, po, line_map)
    receipts = db.get_receipts_for_po(inv.po_number or "", db_path)
    if receipts:
        m.checks.extend(three_way_match(inv, po, receipts, line_map).checks)
    _stage(iid, MATCHED, {"checks": m.to_list(), "line_map": line_map}, db_path)
    dec = decide(v, m, inv)
    _maybe_exception(iid, v, m, dec, db_path)
    _stage(iid, "policy_decided", {"decision": dec.to_dict()}, db_path)
    status = _PARK.get(dec.decision, IN_REVIEW)
    _stage(iid, status, {}, db_path)
    return WorkflowResult(iid, status, dec, v, m, inv)


def process_invoice(path: str | Path, invoice_id: str | None = None,
                    today: date | None = None, db_path: str | None = None) -> WorkflowResult:
    """Full pipeline: ingest → extract → validate → match → policy, persisted."""
    path = Path(path)
    doc = load_document(path)
    inv = extract_invoice(doc)
    iid = invoice_id or path.stem
    dup = db.find_duplicate_invoice(inv.vendor_id or "", inv.invoice_number or "", db_path)
    if dup is not None:
        # 8.6 idempotency: a repeat upload is rejected by the same R001 rule before
        # anything is stored, matched, or approved.
        v = validate_invoice(inv, db.get_vendor(inv.vendor_id or "", db_path),
                             db.get_po(inv.po_number or "", db_path), dup, today)
        dec = decide(v, MatchReport([]), inv)
        db.save_audit_event(dup["invoice_id"], "duplicate_blocked",
                            {"document": str(path), "decision": dec.to_dict()}, db_path)
        return WorkflowResult(iid, REJECTED, dec, v, MatchReport([]), inv)
    _insert_invoice(iid, inv, doc, db_path)
    _stage(iid, RECEIVED, {"document": str(path), "pages": doc.pages,
                           "chars": doc.chars, "quality": doc.quality}, db_path)
    _stage(iid, EXTRACTED, inv.model_dump(mode="json"), db_path)
    return _run_pipeline(iid, inv, today, db_path)


def apply_review_action(invoice_id: str, reviewer: str, action: str, comments: str | None = None,
                        corrections: dict | None = None, today: date | None = None,
                        db_path: str | None = None) -> str | None:
    """§12: approve / reject / correct (re-enters at validation) / request_info."""
    with db.get_conn(db_path) as conn:
        row = conn.execute("SELECT extracted_json FROM invoices WHERE invoice_id=?",
                           (invoice_id,)).fetchone()
    if row is None:
        return None
    if action in _ACTIONS:
        status = _ACTIONS[action]
        with db.get_conn(db_path) as conn:
            conn.execute("UPDATE invoices SET status=? WHERE invoice_id=?", (status, invoice_id))
        if action in ("approve", "reject"):  # a disposition clears the open exception
            _resolve_exceptions(invoice_id, db_path)
    elif action == "correct":
        # merge corrections through the constructor: it validates them (line_items
        # arrive as dicts over the wire), no setattr bypass / serialization warning
        inv = ExtractedInvoice(**{**json.loads(row["extracted_json"]), **(corrections or {})})
        for f in (corrections or {}):
            inv.field_confidence[f] = 1.0  # human-verified beats the AI's self-assessed score
        with db.get_conn(db_path) as conn:
            conn.execute("UPDATE invoices SET extracted_json=? WHERE invoice_id=?",
                         (inv.model_dump_json(), invoice_id))
        _resolve_exceptions(invoice_id, db_path)  # re-opened below if still exceptional
        status = _run_pipeline(invoice_id, inv, today, db_path).status
    else:
        raise ValueError(f"unknown action {action!r}")
    with db.get_conn(db_path) as conn:
        conn.execute("INSERT INTO review_actions (invoice_id, reviewer, action, comments) VALUES (?,?,?,?)",
                     (invoice_id, reviewer, action, comments))
    db.save_audit_event(invoice_id, "review",
                        {"reviewer": reviewer, "action": action, "comments": comments}, db_path)
    return status