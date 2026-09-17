"""Phase 12 — evaluation harness (§15–§16). Mock mode, runs the real pipeline.

Six levels: field accuracy → match accuracy → exception recall → false approvals
→ latency → review time saved. Risk-weighted score per §16 (critical ×5).
"""
import json
import time
from datetime import date
from pathlib import Path

import app.db as db
from app.config import settings
from app.policy.engine import AUTO_APPROVE
from app.workflow.orchestrator import process_invoice

TODAY = date(2026, 9, 15)
SAMPLES = Path(__file__).resolve().parent.parent / "data" / "invoices"


def _ocr_ok() -> bool:
    """d10's expectations flip on whether Tesseract is installed locally."""
    from app.ingest import _ocr_available
    return _ocr_available()

# per-sample expectations: (expected decision, expected statuses per check name)
CASES = {
    "d1_normal": {
        "decision": "MANAGER_REVIEW",  # ¥850k ≥ ¥100k manager band
        "fields_ok": True, "matched": True, "caught": False, "needs_human": True,
    },
    "d2_qty_mismatch": {
        "decision": "EXCEPTION", "fields_ok": True, "matched": False,
        "caught": True, "needs_human": True, "expect_checks": {"quantity": "MISMATCH"},
    },
    "d3_duplicate": {
        "decision": "REJECT", "fields_ok": True, "matched": None,  # blocked pre-insert
        "caught": True, "needs_human": True, "expect_checks": {"duplicate": "DUPLICATE"},
    },
    "d4_bank_change": {
        "decision": "HUMAN_REVIEW", "fields_ok": True, "matched": True,
        "caught": True, "needs_human": True, "expect_checks": {"bank_account": "HIGH_RISK"},
    },
    "d5_missing_po": {
        "decision": "EXCEPTION", "fields_ok": True, "matched": False,
        "caught": True, "needs_human": True, "expect_checks": {"po_exists": "NOT_FOUND"},
    },
    "d6_low_confidence": {
        "decision": "HUMAN_REVIEW", "fields_ok": True, "matched": True,
        "caught": True, "needs_human": True,
    },
    "d7_high_value": {
        "decision": "FINANCE_REVIEW", "fields_ok": True, "matched": True,
        "caught": False, "needs_human": True, "expect_checks": {"total": "MATCH"},
    },
    "d8_currency_mismatch": {
        "decision": "EXCEPTION", "fields_ok": True, "matched": True,
        "caught": True, "needs_human": True, "expect_checks": {"currency": "FAIL"},
    },
    "d9_small": {
        "decision": AUTO_APPROVE, "fields_ok": True, "matched": True,
        "caught": False, "needs_human": False,
    },
    # Image-only scan. Mock extraction reads ground truth either way; with
    # Tesseract the OCR'd text layer gives quality=ok → full confidence →
    # MANAGER_REVIEW (like d1); without it quality=poor caps confidence →
    # R005 HUMAN_REVIEW (which counts as caught).
    "d10_scanned": {
        "decision": "MANAGER_REVIEW" if _ocr_ok() else "HUMAN_REVIEW",
        "fields_ok": True, "matched": True,
        "caught": not _ocr_ok(), "needs_human": True,
    },
}


# §16 critical fields — errors here weigh ×5 in the score
CRITICAL = ("total_amount", "bank_account", "vendor_name", "vendor_id")


def _fields_ok(ext: dict, gt: dict) -> tuple[bool, list[str]]:
    wrong = []
    for f, want in gt.items():
        if f == "line_items":
            got = [(li["description"], li["quantity"], li["unit_price"]) for li in ext.get(f, [])]
            want = [(li["description"], li["quantity"], li["unit_price"]) for li in want]
        else:
            got = ext.get(f)
        if got != want:
            wrong.append(f)
    return not wrong, wrong


def run_eval(db_path: str | None = None, today: date = TODAY) -> dict:
    db.seed(db_path)
    results, t0 = {}, time.perf_counter()
    for name, exp in CASES.items():
        t = time.perf_counter()
        r = process_invoice(SAMPLES / f"{name}.pdf", today=today, db_path=db_path)
        elapsed = time.perf_counter() - t
        gt = json.loads((SAMPLES / f"{name}_ground_truth.json").read_text(encoding="utf-8"))
        ext = json.loads(r.extracted.model_dump_json())

        ok, wrong = _fields_ok(ext, gt)
        crit_wrong = [f for f in wrong if f in CRITICAL]
        checks = {c.name: c.status for c in [*r.validation.checks, *r.match.checks]}
        # Level 2 judges the match report only — bank/currency are validation
        # dimensions (§16 Level 2 = PO/line/qty/price/three-way), not match dims.
        matched = all(c.status in ("MATCH", "PASS", "SKIP") for c in r.match.checks)

        results[name] = {
            "decision": r.decision.decision, "expected_decision": exp["decision"],
            "decision_correct": r.decision.decision == exp["decision"],
            "fields": {"ok": ok, "wrong": wrong, "critical_wrong": crit_wrong},
            "matched": matched, "matched_correct": (exp["matched"] is None
                                                    or matched == exp["matched"]),
            "caught": r.decision.decision not in (AUTO_APPROVE, "MANAGER_REVIEW",
                                                  "FINANCE_REVIEW"),
            "caught_correct": (exp["caught"] == (r.decision.decision not in
                                                 (AUTO_APPROVE, "MANAGER_REVIEW",
                                                  "FINANCE_REVIEW"))),
            "false_approval": (exp["needs_human"]
                                and r.decision.decision == AUTO_APPROVE),
            "check_expectations": {n: checks.get(n) for n in exp.get("expect_checks", {})},
            "latency_s": round(elapsed, 4),
        }
    return _summarize(results, time.perf_counter() - t0)


def _summarize(results: dict, total_s: float) -> dict:
    n = len(results)
    lat = sorted(r["latency_s"] for r in results.values())
    p95 = lat[int(0.95 * (n - 1))]
    field_total = sum(len(r["fields"]["wrong"]) for r in results.values())
    crit_total = sum(len(r["fields"]["critical_wrong"]) for r in results.values())
    recall = sum(1 for r in results.values() if r["caught_correct"]) / n
    false_pos = sum(r["false_approval"] for r in results.values())
    decision_acc = sum(r["decision_correct"] for r in results.values()) / n
    matched_acc = sum(1 for r in results.values() if r["matched_correct"]) / n
    # §16 risk-weighted: critical-field error = 5 field errors
    weighted = field_total + 4 * crit_total  # counts each critical error 5× total
    # L6: review time saved — without AI every invoice is human-reviewed
    with_ai = sum(CASES[k]["needs_human"] for k in results)
    saved = n - with_ai
    return {
        "summary": {
            "decision_accuracy": round(decision_acc, 3),
            "match_accuracy": round(matched_acc, 3),
            "exception_recall": round(recall, 3),
            "false_approvals": false_pos,
            "field_errors": field_total,
            "critical_field_errors": crit_total,
            "weighted_field_errors": weighted,
            "latency_avg_s": round(sum(lat) / n, 4),
            "latency_p95_s": round(p95, 4),
            "total_time_s": round(total_s, 2),
            "review_time_saved_pct": round(100 * saved / n, 1),
        },
        "per_invoice": results,
    }


if __name__ == "__main__":
    dbp = Path("data/eval.db").resolve()
    dbp.unlink(missing_ok=True)  # fresh DB each run; stale rows = false duplicates
    out = run_eval(str(dbp))
    (Path("evaluation") / "results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md = ["# DocFlow evaluation report", "",
          "| metric | value |", "|---|---|"]
    for k, v in out["summary"].items():
        md.append(f"| {k} | {v} |")
    (Path("evaluation") / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"OK: {len(out['per_invoice'])} invoices; "
          f"decision_acc={out['summary']['decision_accuracy']} "
          f"recall={out['summary']['exception_recall']} "
          f"false_approvals={out['summary']['false_approvals']}")