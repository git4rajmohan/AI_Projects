# Phase 9 — Evaluation. Pure scoring core (metrics / CSV text) with NO network
# and NO streamlit imports — unit-testable by import. The one network function
# is run_scenario, wrapping services.tev1_service.call_tev1 (spec section 13);
# results reuse the Phase-4 summarize_tev1 normalization, so every value that
# comes back is a real API value — nothing is fabricated here either.
import csv
import json
from datetime import datetime
from io import StringIO
from pathlib import Path

from prompts import MODE_TEMPLATES, autofill_criteria
from prompts import build_decision_request
from prompts import custom as custom_mode
from services.result_processor import summarize_tev1
from services.tev1_service import Tev1Error, call_tev1

SCENARIOS_PATH = Path("evaluation") / "scenarios.json"
EXPORTS_DIR = Path("evaluation") / "exports"

# Column order for the results table and the exported CSV (spec section 21).
RESULTS_HEADER = ["input", "expected", "actual", "confidence_pct",
                  "correct", "response_time_s", "error"]


def load_scenarios():
    """Read evaluation/scenarios.json; keep only rows the runner can use.

    Raises ValueError with an actionable message on corrupt/invalid JSON or a
    non-list root (the UI invites hand-editing the file — never a traceback).
    """
    if not SCENARIOS_PATH.exists():
        return []
    try:
        data = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"evaluation/scenarios.json is not valid JSON ({exc}). Fix it in an "
            "editor, then reload this page."
        ) from None  # ponytail: chain swallows the noisy context, message is enough
    if not isinstance(data, list):
        raise ValueError(
            "evaluation/scenarios.json must contain a list of scenario rows — "
            "currently it does not. Fix it in an editor, then reload this page."
        )
    return [r for r in data
            if isinstance(r, dict) and (r.get("input") or "").strip() and (r.get("mode") or "").strip()]


def load_scenarios_safe() -> tuple:
    """Same rows as load_scenarios, but never raises from the UI path:
    corrupt/invalid content becomes (empty list, friendly message)."""
    try:
        return load_scenarios(), None
    except ValueError as exc:  # corrupt file — surface, don't crash the page
        return [], str(exc)


def save_scenarios(rows: list) -> None:
    SCENARIOS_PATH.parent.mkdir(exist_ok=True)
    SCENARIOS_PATH.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def decision_request_for(row: dict) -> dict:
    """Build the {state, questions} pair for one scenario row.

    Raises ValueError with a user-facing message (CustomModeError is one).
    """
    mode = (row.get("mode") or "").strip()
    input = row.get("input") or ""
    if mode == "Custom":
        c = row.get("custom") or {}
        config = custom_mode.validate_config(
            c.get("question", ""), c.get("type", ""),
            ", ".join(c.get("choices") or []), c.get("criteria_text", ""))
        return {
            "state": input,
            "questions": {"decision": custom_mode.build_question(
                config, autofill_criteria=autofill_criteria)},
        }
    template = MODE_TEMPLATES.get(mode)
    if template is None:
        raise ValueError(
            f"Unknown mode '{mode}'. Use one of: "
            + ", ".join([*sorted(MODE_TEMPLATES), "Custom"]) + ".")
    return build_decision_request(template[0], input)


def run_scenario(row: dict) -> dict:
    """Run one row through Tev1; returns real values or {"error": message}."""
    try:
        request = decision_request_for(row)
    except ValueError as exc:
        return {"error": str(exc)}
    try:
        summary = summarize_tev1(call_tev1(request["state"], request["questions"]))
    except Tev1Error as exc:
        return {"error": str(exc)}
    except Exception as exc:  # one bad row must never crash the whole page run
        return {"error": f"Unexpected error in scenario runner: {exc}"}
    return {
        "error": None,
        "actual": summary.get("decision"),
        "confidence": summary.get("confidence"),
        "response_time_s": summary.get("elapsed_s"),
    }


def is_low_confidence(confidence, threshold) -> bool:
    """Spec section 19 low-confidence rule: strictly below an applied threshold."""
    return (isinstance(threshold, (int, float)) and threshold > 0
            and isinstance(confidence, (int, float))
            and confidence < threshold)


def build_rows(scenario_rows: list, results: list) -> list:
    """Zip scenario rows with run results into display/CSV rows (correct is
    None for rows with no expected value — spec section 21 stores both)."""
    display = []
    for row, res in zip(scenario_rows, results):
        conf = res.get("confidence")
        expected = row.get("expected")
        correct = None
        if not res.get("error") and expected:
            # scored ONLY when the row has a non-empty expected value; rows
            # without one stay unscored — a guess would be a fabricated value.
            correct = (str(res.get("actual")).strip().lower()
                       == str(expected).strip().lower())
        display.append({
            "input": row.get("input"),
            "expected": expected or "",
            "actual": res.get("actual") or "",
            "confidence_pct": round(conf * 100, 1) if isinstance(conf, (int, float)) else None,
            "correct": correct,
            "response_time_s": res.get("response_time_s"),
            "error": res.get("error"),
            "low_confidence": is_low_confidence(conf, row.get("confidence_threshold")),
        })
    return display


def metrics(display_rows: list) -> dict:
    """Spec section 21 aggregate metrics — real values only, never fabricated."""
    scored = [r for r in display_rows if r["correct"] is not None]
    confs = [r["confidence_pct"] for r in display_rows
             if isinstance(r["confidence_pct"], (int, float))]
    times = [r["response_time_s"] for r in display_rows
             if isinstance(r["response_time_s"], (int, float))]
    return {
        "correct": sum(1 for r in scored if r["correct"]),
        "scored": len(scored),
        "accuracy_pct": (round(100 * sum(1 for r in scored if r["correct"]) / len(scored), 1)
                         if scored else None),
        "avg_confidence_pct": (round(sum(confs) / len(confs), 1) if confs else None),
        "avg_response_time_s": (round(sum(times) / len(times), 2) if times else None),
    }


def to_csv_string(display_rows: list) -> str:
    """The exported table — results only; the API key never appears anywhere."""
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(RESULTS_HEADER)
    for r in display_rows:
        writer.writerow([r[col] for col in RESULTS_HEADER])
    return buf.getvalue()


def write_export(display_rows: list) -> Path:
    """Persist the results CSV under evaluation/exports/ (gitignored)."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"eval_{datetime.now():%Y%m%d_%H%M%S}.csv"
    path = EXPORTS_DIR / name
    path.write_text(to_csv_string(display_rows), encoding="utf-8")
    return path


if __name__ == "__main__":
    # Self-check: scoring, metrics, low-confidence rule, CSV header — synthetic
    # rows only, no network, no file writes.
    rows = load_scenarios()
    assert rows, "scenarios.json should have seeds"
    fake = [
        {"error": None, "actual": "duplicate_charge", "confidence": 0.97, "response_time_s": 1.5},
        {"error": None, "actual": "duplicate_charge", "confidence": 0.4, "response_time_s": 2.0},
        {"error": "Tev1 down", "actual": None, "confidence": None, "response_time_s": None},
        {"error": None, "actual": "nonexistent_choice", "confidence": None, "response_time_s": 0.8},
    ]
    fake_rows = [
        {**rows[0], "expected": "duplicate_charge", "confidence_threshold": 0.9},
        {**rows[1], "expected": "none", "confidence_threshold": 0.9},
        rows[2],
        rows[3],
    ]
    display = build_rows(fake_rows, fake)
    assert display[0]["correct"] is True
    assert display[0]["low_confidence"] is False
    assert display[1]["correct"] is False
    assert display[1]["low_confidence"] is True
    assert display[2]["error"] == "Tev1 down"
    assert display[3]["correct"] is None  # no expected value — never scored
    m = metrics(display)
    assert m == {"correct": 1, "scored": 2, "accuracy_pct": 50.0,
                 "avg_confidence_pct": 68.5, "avg_response_time_s": 1.43}
    text = to_csv_string(display)
    assert text.splitlines()[0] == ",".join(RESULTS_HEADER)
    assert "duplicate_charge" in text

    # Phase 10 guard: corrupt/hand-edited scenarios.json (synthetic content on a
    # temp path — the real file is never touched).
    import tempfile
    orig = SCENARIOS_PATH
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "scenarios.json"
        SCENARIOS_PATH = tmp
        tmp.parent.mkdir(exist_ok=True)
        for payload, expect_raise in (
            ('{"broken', True),  # invalid JSON
            ("not-a-list", True),  # valid JSON, wrong root type
            ('[{"mode":"Customer Support","input":"x","expected":null}]', False),
        ):
            tmp.write_text(payload, encoding="utf-8")
            try:
                load_scenarios()
                assert not expect_raise, f"expected ValueError for {payload!r}"
            except ValueError as exc:
                assert expect_raise and "scenario" in str(exc).lower()
            rows_safe, msg = load_scenarios_safe()
            assert bool(msg) == expect_raise, f"safe msg mismatch for {payload!r}: {msg!r}"
            if not expect_raise:
                assert len(rows_safe) == 1, "valid payload must parse to one row"
            else:
                assert rows_safe == [], "corrupt payload must yield no rows"
    SCENARIOS_PATH = orig
    print("evaluation self-check OK:", m)