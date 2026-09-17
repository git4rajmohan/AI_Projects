"""Phase 10 — FastAPI backend (§10).

Thin wire over the Phase 8 orchestrator and Phase 9 audit reader: upload runs
the pipeline, review posts reviewer actions, everything else reads SQLite and
returns the JSON documents those modules already produce. Request/response
shapes live in models.py; no raw dicts cross the wire.
"""
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import app.db as db
from app.audit.recorder import build_audit_report
from app.api.models import InvoiceListRow, ReviewIn, ReviewOut, UploadOut
from app.extraction.ingest_error import IngestError
from app.workflow.orchestrator import WorkflowResult, apply_review_action, process_invoice

app = FastAPI(title="DocFlow Invoice Approval", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

UPLOAD_DIR = Path("data/uploads")  # ponytail: flat dir keyed by invoice_id stem; per-day/tenant split if needed


def _detail(iid: str) -> dict:
    """One-glance §13 payload: extraction, validation, match, decision, exceptions."""
    report = build_audit_report(iid)
    if report is None:
        raise HTTPException(404, f"invoice {iid!r} not found")
    by_stage = {e["stage"]: e["payload"] for e in report["events"]}
    decision = by_stage.get("policy_decided", {}).get("decision", {})
    po_lines = {}  # line_id -> PO line row, for the UI's invoice-vs-PO table
    ext = by_stage.get("extracted") or {}
    if ext.get("po_number"):
        po = db.get_po(ext["po_number"])
        po_lines = {l["line_id"]: l for l in (po or {}).get("lines", [])}
    return {
        "invoice_id": iid,
        "status": report["final_status"],
        "document_path": report["document_path"],
        "extraction": ext,
        "validation": by_stage.get("validated", {}).get("checks", []),
        "match": by_stage.get("matched", {}).get("checks", []),
        "line_map": by_stage.get("matched", {}).get("line_map", {}),
        "po_lines": po_lines,
        "decision": decision.get("decision"),
        "rule_id": decision.get("rule_id"),
        "reasons": [r["text"] for r in decision.get("reasons", [])],
        "exceptions": report["exceptions"],
        "review_actions": report["review_actions"],
    }


def _result_out(r: WorkflowResult) -> dict:
    return {"invoice_id": r.invoice_id, "status": r.status, "decision": r.decision.decision,
            "rule_id": r.decision.rule_id, "reasons": [x.text for x in r.decision.reasons]}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/invoices/upload", response_model=UploadOut)
def upload(file: UploadFile) -> dict:
    """Save the PDF, run the full pipeline. 422 + exception row for unreadable docs."""
    iid = Path(file.filename or "uploaded.pdf").stem
    dest = UPLOAD_DIR / file.filename
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        r = process_invoice(dest, invoice_id=iid)
    except IngestError as e:
        db.init_db()
        with db.get_conn() as conn:  # §10.3: unreadable doc still leaves a trace
            conn.execute("INSERT INTO exceptions (invoice_id, type, severity, reason)"
                         " VALUES (?,?,?,?)", (iid, "ingest_error", "high", str(e)))
        db.save_audit_event(iid, "ingest_failed", {"document": str(dest), "error": str(e)})
        raise HTTPException(422, str(e)) from e
    return _result_out(r)


@app.get("/invoices", response_model=list[InvoiceListRow])
def list_invoices(status: str | None = None) -> list[dict]:
    with db.get_conn() as conn:
        sql = ("SELECT invoice_id, invoice_number, vendor_id, total, currency, status"
               " FROM invoices" + (" WHERE status=?" if status else "") + " ORDER BY invoice_id")
        return [dict(r) for r in conn.execute(sql, (status,) if status else ())]


@app.get("/invoices/{iid}", response_model=None)
def invoice_detail(iid: str) -> dict:
    return _detail(iid)


@app.get("/invoices/{iid}/audit")
def invoice_audit(iid: str) -> dict:
    report = build_audit_report(iid)
    if report is None:
        raise HTTPException(404, f"invoice {iid!r} not found")
    return report


@app.get("/invoices/{iid}/document")
def invoice_document(iid: str) -> FileResponse:
    path = _detail(iid)["document_path"]
    if not path or not Path(path).exists():
        raise HTTPException(404, "document file missing")
    return FileResponse(path, media_type="application/pdf")  # inline, not attachment


@app.post("/invoices/{iid}/review", response_model=ReviewOut)
def review(iid: str, body: ReviewIn) -> dict:
    try:
        status = apply_review_action(iid, body.reviewer, body.action,
                                     body.comments, body.corrections)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if status is None:
        raise HTTPException(404, f"invoice {iid!r} not found")
    return {"invoice_id": iid, "status": status}


@app.delete("/invoices/{iid}")
def delete_invoice(iid: str) -> dict:
    """Demo helper: wipe an invoice so its document can be re-uploaded fresh."""
    try:
        ok = db.delete_invoice(iid)
    except ValueError as e:
        raise HTTPException(403, str(e)) from e
    if not ok:
        raise HTTPException(404, f"invoice {iid!r} not found")
    return {"deleted": iid}


@app.get("/exceptions")
def open_exceptions() -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT e.exception_id, e.invoice_id, e.type, e.severity, e.reason, e.created_at,"
            " i.total, i.currency, i.status AS invoice_status"
            " FROM exceptions e LEFT JOIN invoices i USING (invoice_id)"
            " WHERE e.status='open' ORDER BY e.exception_id").fetchall()
    return [dict(r) for r in rows]