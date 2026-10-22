# Phase 13 — evaluation service tests (plan 13.V): deterministic generator,
# mocked batch runner, hand-computed metrics, holdout isolation, clean CSV.

import csv
from io import StringIO

import maintai.evaluation_service as ev


def test_generate_100_deterministic_labelled_cases():
    a = ev.generate_cases()
    b = ev.generate_cases()          # same seed -> identical labels + values
    strip = lambda cases: [(c["case_id"], c["case_type"],
                            c["reading"]["temperature_c"], c["expected_action"],
                            c["expected_review"], c["tev1_reply"])
                           for c in cases]
    assert strip(a["tuning"]) == strip(b["tuning"])
    assert strip(a["holdout"]) == strip(b["holdout"])
    total = len(a["tuning"]) + len(a["holdout"])
    assert total >= 100
    types = {c["case_type"] for c in a["tuning"] + a["holdout"]}
    assert types == {"normal", "warning", "critical", "missing_data", "ambiguous"}
    # labels come from case structure, not model output
    for c in a["tuning"] + a["holdout"]:
        assert c["expected_action"] == ev.CASE_ACTIONS[c["case_type"]]
        assert c["expected_review"] == ev.EXPECTED_REVIEW[c["case_type"]]


def test_holdout_excluded_from_run():
    cases = ev.generate_cases(per_type=20)
    tuning_ids = {c["case_id"] for c in cases["tuning"]}
    holdout_ids = {c["case_id"] for c in cases["holdout"]}
    assert not tuning_ids & holdout_ids and holdout_ids  # disjoint, non-empty
    rows = ev.run_evaluation(cases["tuning"])           # only the tuning slice
    assert {r["case_id"] for r in rows} == tuning_ids


def test_metrics_match_hand_computed_mini_set():
    # 4 cases: 2 monitor->monitor, 1 inspect->urgent (miss), 1 missing->review
    cases = [
        ev._make_case("normal", 0, __import__("random").Random(1)),   # monitor/monitor
        ev._make_case("normal", 1, __import__("random").Random(1)),   # monitor/monitor
        ev._make_case("warning", 0, __import__("random").Random(1)),  # inspect expected
        ev._make_case("missing_data", 3, __import__("random").Random(1)),
    ]
    # force one classification error: the warning case answers 'urgent_maintenance'
    cases[2]["tev1_reply"]["answers"]["maintenance_action"]["choice"] = \
        "urgent_maintenance"
    rows = ev.run_evaluation(cases)
    m = ev.metrics(rows)
    # hand-computed: accuracy 3/4; inspect recall 0/1, precision undefined->0
    assert m["n_cases"] == 4
    assert m["accuracy"] == 0.75
    assert m["per_class_recall"]["inspect"] == 0.0
    assert m["per_class_precision"]["inspect"] == 0.0
    assert m["per_class_recall"]["monitor"] == 1.0
    cm = m["confusion_matrix"]
    labels = m["labels"]
    assert cm[labels.index("monitor")][labels.index("monitor")] == 2
    assert cm[labels.index("inspect")][labels.index("urgent_maintenance")] == 1
    assert m["human_review_rate"] == 0.5          # missing + misratched urgent
    assert m["unavailable_or_invalid_rate"] == 0.25
    assert m["avg_tev1_latency_ms"] > 0
    assert m["avg_llm_latency_ms"] is None


def test_missing_data_and_ambiguous_route_insufficient():
    cases = [ev._make_case("missing_data", 0, __import__("random").Random(1)),
             ev._make_case("ambiguous", 0, __import__("random").Random(1)),
             ev._make_case("ambiguous", 1, __import__("random").Random(1))] \
        + [ev._make_case("ambiguous", 2, __import__("random").Random(1))]
    for c in cases[2:]:
        c["tev1_reply"] = ev._tev1_reply("ambiguous", 2, 0.5)  # variant A+B mix
    rows = ev.run_evaluation(cases[:2])
    assert all(r["final_action"] == "insufficient_data" for r in rows)
    assert all(r["review_required"] for r in rows)
    assert all(r["correct"] for r in rows)


def test_review_is_only_signal_confidence_never_scores():
    """13.5: low-confidence ambiguous case still ends in a review-required
    outcome — confidence never modifies the action label itself."""
    case = ev._make_case("ambiguous", 1, __import__("random").Random(1))
    case["tev1_reply"]["answers"]["maintenance_action"]["confidence"] = 0.55
    row = ev.run_case(case)
    assert row["review_required"] is True
    assert row["final_action"] == "insufficient_data"


def test_run_evaluation_tev1_error_becomes_review_row():
    def broken(state, questions):
        raise RuntimeError("connection refused")
    cases = ev.generate_cases(per_type=2)["tuning"]
    rows = ev.run_evaluation(cases, run_tev1=broken)
    # normal case: valid data, dead model -> policy UNAVAILABLE, review, no crash
    urgent_rows = [r for r in rows if r["case_type"] == "normal"]
    assert all(r["final_action"] == "insufficient_data" for r in urgent_rows)
    assert all(r["review_required"] for r in urgent_rows)


def test_csv_export_clean():
    rows = ev.run_evaluation(ev.generate_cases(per_type=3)["tuning"])
    text = ev.to_csv_string(rows)
    table = list(csv.reader(StringIO(text)))
    assert table[0][0] == "case_id" and table[0][4] == "final_action"
    assert len(table) == len(rows) + 1
    joined = text.lower()
    for secret in ("api_key", "authorization", "ollama_api", "sk-"):
        assert secret not in joined


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))