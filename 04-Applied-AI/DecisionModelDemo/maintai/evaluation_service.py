# Evaluation service (spec1 §13 evaluation dataset; plan Phase 13). Generates
# ≥100 deterministic labelled cases (labels from generator parameters, never
# from model output), runs each through the real validation→rules→Tev1→policy
# ladder with an injectable (mockable) Tev1 callable, and scores with
# scikit-learn. A fixed holdout slice is generated but excluded from the
# default run. Confidence is used only as a review signal (spec1 §5.5).

import random
from datetime import datetime, timedelta
from statistics import mean

from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from config.settings import SENSOR_FRESHNESS_MINUTES
from maintai.maintenance_service import PolicyOutcome, apply_policy
from maintai.models import MachineLimits, SensorReading, validate_reading
from maintai.prompts import interpret_tev1
from maintai.rules_engine import RuleReport, evaluate_machine

# The four canonical final actions — the confusion-matrix label space.
EVAL_ACTIONS = ["monitor", "inspect", "urgent_maintenance", "insufficient_data"]

# True condition -> action the pipeline SHOULD produce (with the coherent
# injected Tev1 reply this generator ships). missing/ambiguous both route to
# insufficient_data, distinguished by review_required.
CASE_ACTIONS = {"normal": "monitor", "warning": "inspect",
                "critical": "urgent_maintenance",
                "missing_data": "insufficient_data",
                "ambiguous": "insufficient_data"}
EXPECTED_REVIEW = {"normal": False, "warning": False, "critical": True,
                   "missing_data": True, "ambiguous": True}

MACHINE_TYPES = ["Bearing test rig", "Industrial mixer", "Centrifugal pump",
                 "Electric motor", "Reciprocating compressor"]


def _tev1_reply(case_type, i, elapsed_s):
    """Deterministic canned answer set: coherent with the case's true label
    (ambiguous cases are deliberately low-confidence or self-contradicting)."""
    actions = {"normal": ("monitor", 0.95, 0.05), "warning": ("inspect", 0.90, 0.60),
               "critical": ("urgent_maintenance", 0.97, 0.95)}
    if case_type in actions:
        action, confidence, anomaly = actions[case_type]
    elif i % 2 == 0:  # ambiguous variant A: 'monitor' contradicted by anomaly
        action, confidence, anomaly = "monitor", 0.90, 0.80
    else:             # ambiguous variant B: coherent action, low confidence
        action, confidence, anomaly = "inspect", 0.55, 0.30
    return {"model": "canned-eval", "elapsed_s": elapsed_s, "answers": {
        "maintenance_action": {"type": "choice", "choice": action,
                               "probabilities": {action: confidence},
                               "confidence": confidence},
        "anomaly_present": {"type": "noul", "noul": anomaly},
        "severity": {"type": "score", "score": 0.4,
                     "legend": {"0": "Normal"}, "probabilities": {"0": 0.9},
                     "confidence": 0.9}}}


def _make_case(case_type, i, rnd):
    jitter = rnd.uniform(-0.3, 0.3)
    values = {"normal": {"temperature_c": 70.0 + jitter,   # below warning 75
                         "vibration_mm_s": 3.0, "motor_load_percent": 70.0,
                         "rpm": 1780.0, "operating_hours": 1000.0},
              "warning": {"temperature_c": 80.0 + jitter,  # 75..90 window
                          "vibration_mm_s": 3.0, "motor_load_percent": 70.0,
                          "rpm": 1780.0, "operating_hours": 1001.0},
              "critical": {"temperature_c": 92.0,          # above critical 90
                           "vibration_mm_s": 3.0, "motor_load_percent": 70.0,
                           "rpm": 1780.0, "operating_hours": 1002.0},
              "missing_data": {"temperature_c": 70.0,      # vibration absent
                               "vibration_mm_s": None,
                               "motor_load_percent": 70.0, "rpm": 1780.0,
                               "operating_hours": 1003.0},
              "ambiguous": {"temperature_c": 68.0 + jitter,  # healthy readings…
                            "vibration_mm_s": 2.8, "motor_load_percent": 68.0,
                            "rpm": 1780.0, "operating_hours": 1004.0}}[case_type]
    reading = {"machine_id": f"EVAL-{case_type.upper()}-{i:03d}",
               "machine_type": MACHINE_TYPES[i % len(MACHINE_TYPES)],
               "timestamp": datetime.now() - timedelta(minutes=10),
               "data_source": "synthetic (evaluation)", **values}
    return {
        "case_id": f"{case_type}-{i:03d}",
        "case_type": case_type,
        "machine_type": reading["machine_type"],
        "reading": reading,
        "limits": MachineLimits().model_dump(),
        "tev1_reply": _tev1_reply(case_type, i, elapsed_s=round(0.5 + i / 100, 3)),
        "expected_action": CASE_ACTIONS[case_type],
        "expected_review": EXPECTED_REVIEW[case_type],
    }


def generate_cases(per_type: int = 20, holdout_every: int = 10,
                   seed: int = 13) -> dict:
    """5 synthetic scenarios x per_type cases = ≥100 deterministic labelled
    cases, split into the run slice and a fixed holdout (every holdout_every-th
    case; reserved for final evaluation, never included in the default run)."""
    rnd = random.Random(seed)
    tuning, holdout = [], []
    n = 0
    for case_type in ("normal", "warning", "critical", "missing_data", "ambiguous"):
        for i in range(per_type):
            n += 1
            (holdout if n % holdout_every == 0 else tuning).append(
                _make_case(case_type, i, rnd))
    return {"tuning": tuning, "holdout": holdout}


def run_case(case: dict, run_tev1=None,
             freshness_minutes: float = SENSOR_FRESHNESS_MINUTES) -> dict:
    """One case through validation → rules → Tev1 → policy (no db, no LLM).
    run_tev1(state, questions) injects a canned reply; None = case's own.
    A raising/malformed Tev1 callable -> tev1 None -> policy UNAVAILABLE
    (review-required), mirroring run_decision — never a safe outcome."""
    reading = SensorReading.model_validate(case["reading"])
    limits = MachineLimits(**case["limits"])
    validation = validate_reading(reading, limits, freshness_minutes)
    if not validation.ok:
        outcome = apply_policy(validation, RuleReport(), None)
        return _row(case, outcome, None, validation.status)
    report = evaluate_machine(reading, limits)  # single-point cases: no history
    def reply(_state, _questions, case=case):
        return case["tev1_reply"]
    try:
        tev1 = interpret_tev1((run_tev1 or reply)(None, None))
    except Exception:  # noqa: BLE001 — dead model is a row, not a crash (spec1 §14)
        tev1 = None
    outcome = apply_policy(validation, report, tev1)
    return _row(case, outcome, tev1, None)


def _row(case, outcome, tev1, error_status):
    return {"case_id": case["case_id"], "case_type": case["case_type"],
            "machine_type": case["machine_type"],
            "expected_action": case["expected_action"],
            "final_action": outcome.final_action,
            "correct": outcome.final_action == case["expected_action"],
            "review_required": outcome.human_review_required,
            "expected_review": case["expected_review"],
            "review_as_expected": (outcome.human_review_required
                                   == case["expected_review"]),
            "latency_ms": (tev1.elapsed_s * 1000 if tev1 and tev1.elapsed_s
                           else None),
            "error_status": error_status}


def run_evaluation(cases: list, run_tev1=None) -> list:
    """Batch runner (plan 13.2). The holdout slice is simply not passed."""
    return [run_case(case, run_tev1) for case in cases]


def metrics(rows: list, review_threshold_served: float = None) -> dict:
    """Classification + operations metrics (plan 13.3, sklearn). Confidence
    appears only as the review signal it is (13.5): never a correctness score."""
    expected = [r["expected_action"] for r in rows]
    actual = [r["final_action"] for r in rows]
    precision, recall, _, _ = precision_recall_fscore_support(
        expected, actual, labels=EVAL_ACTIONS, zero_division=0)
    cm = confusion_matrix(expected, actual, labels=EVAL_ACTIONS)
    by_type = {}
    for r in rows:
        bucket = by_type.setdefault(r["machine_type"], {"n": 0, "correct": 0})
        bucket["n"] += 1
        bucket["correct"] += r["correct"]
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    unavailable = sum(1 for r in rows if r["error_status"])
    return {
        "n_cases": len(rows),
        "accuracy": round(sum(1 for r in rows if r["correct"]) / len(rows), 3)
        if rows else None,
        "per_class_precision": dict(zip(EVAL_ACTIONS,
                                        (round(p, 3) for p in precision))),
        "per_class_recall": dict(zip(EVAL_ACTIONS,
                                     (round(r, 3) for r in recall))),
        "confusion_matrix": cm.tolist(),
        "labels": EVAL_ACTIONS,
        "human_review_rate": round(sum(1 for r in rows
                                       if r["review_required"]) / len(rows), 3)
        if rows else None,
        "review_agreement": round(sum(1 for r in rows
                                      if r["review_as_expected"]) / len(rows), 3)
        if rows else None,
        "unavailable_or_invalid_rate": round(unavailable / len(rows), 3)
        if rows else None,
        "avg_tev1_latency_ms": round(mean(latencies), 1) if latencies else None,
        "avg_llm_latency_ms": None,  # explanations disabled in batch runs
        "by_machine_type": {k: round(v["correct"] / v["n"], 3)
                            for k, v in sorted(by_type.items())},
    }


def to_csv_string(rows: list) -> str:
    """Full per-case results table for export. No key/secret fields exist here
    by construction (case ids, actions, latencies only)."""
    import csv as _csv
    from io import StringIO
    buf = StringIO()
    writer = _csv.writer(buf)
    header = ["case_id", "case_type", "machine_type", "expected_action",
              "final_action", "correct", "review_required", "expected_review",
              "latency_ms", "error_status"]
    writer.writerow(header)
    for r in rows:
        writer.writerow([r[col] for col in header])
    return buf.getvalue()