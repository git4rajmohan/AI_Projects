"""Phase 9 — audit reconstruction (§14) + explainability (§13).

The WRITE side lives in the orchestrator: every pipeline stage and reviewer
action appends to the audit_events table via db.save_audit_event(). This module
is the READ side: rebuild the full decision story from the log alone — no live
re-computation — as plain JSON-serializable dicts.
"""
import json

import app.db as db


def build_audit_report(invoice_id: str, db_path: str | None = None) -> dict | None:
    """Ordered §14 reconstruction: doc, extracted fields, validation, match,
    policy + rule_ids, exceptions, reviewer actions, final decision."""
    with db.get_conn(db_path) as conn:
        inv = conn.execute("SELECT status, document_path FROM invoices WHERE invoice_id=?",
                           (invoice_id,)).fetchone()
        if inv is None:
            return None
        events = conn.execute(
            "SELECT stage, payload_json, timestamp FROM audit_events"
            " WHERE invoice_id=? ORDER BY event_id", (invoice_id,)).fetchall()
        exceptions = conn.execute(
            "SELECT type, severity, reason, status, created_at FROM exceptions"
            " WHERE invoice_id=? ORDER BY exception_id", (invoice_id,)).fetchall()
        reviews = conn.execute(
            "SELECT reviewer, action, comments, timestamp FROM review_actions"
            " WHERE invoice_id=? ORDER BY review_id", (invoice_id,)).fetchall()
    return {
        "invoice_id": invoice_id,
        "document_path": inv["document_path"],
        "final_status": inv["status"],
        # ponytail: no document versioning in v1 — document_path + the received event identify the input
        "events": [{"stage": e["stage"], "timestamp": e["timestamp"],
                    "payload": json.loads(e["payload_json"])} for e in events],
        "exceptions": [dict(e) for e in exceptions],
        "review_actions": [dict(r) for r in reviews],
    }


def explain(report: dict) -> dict:
    """§13 one-glance payload: what was extracted / validated / matched / which policy / why."""
    by_stage = {e["stage"]: e["payload"] for e in report["events"]}
    extracted = by_stage.get("extracted", {})
    decision = by_stage.get("policy_decided", {}).get("decision", {})
    return {
        "extracted": {k: v for k, v in extracted.items()
                      if k not in ("field_confidence", "quality", "extraction_inconsistent")},
        "confidence": extracted.get("field_confidence", {}),
        "validated": by_stage.get("validated", {}).get("checks", []),
        "matched": by_stage.get("matched", {}).get("checks", []),
        "decision": decision.get("decision"),
        "rule_id": decision.get("rule_id"),
        "why": [r["text"] for r in decision.get("reasons", [])],
        "reviewed_by": [f"{r['reviewer']}:{r['action']}" for r in report["review_actions"]],
        "final_status": report["final_status"],
    }