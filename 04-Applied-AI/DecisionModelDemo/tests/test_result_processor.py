# Phase 11 — Result processor tests (plan 11.1). Synthetic dicts only, no network.

from services.result_processor import (build_comparison, format_probabilities,
                                       summarize_llm, summarize_tev1,
                                       total_elapsed_s)

TEV1 = {
    "model": "fake-tev1",
    "answers": {
        "intent": {"type": "choice", "choice": "duplicate_charge",
                   "probabilities": {"duplicate_charge": 0.9942, "none": 0.33,
                                     "card_declined": 0.01,
                                     "cancel_subscription": 0.0025},
                   "confidence": 0.983},
        "urgency": {"type": "choice", "choice": "medium"},
    },
    "elapsed_s": 0.82,
    "usage": {"input_tokens": 164, "output_tokens": 1},
}
LLM = {"text": "ok", "model": "fake-llm", "elapsed_s": 4.31,
       "prompt_tokens": 18, "eval_tokens": 70}


def test_summarize_tev1():
    t = summarize_tev1(TEV1)
    assert t["question"] == "intent" and t["decision"] == "duplicate_charge"
    assert t["confidence"] == 0.983
    assert t["probabilities"][0] == ("duplicate_charge", 0.9942)   # sorted descending
    assert t["probabilities"][1] == ("none", 0.33)
    assert t["extra_answers"] == {"urgency": ("medium", None)}
    assert t["input_tokens"] == 164 and t["output_tokens"] == 1
    assert t["elapsed_s"] == 0.82 and t["model"] == "fake-tev1"


def test_summarize_llm():
    l = summarize_llm(LLM)
    assert l["text"] == "ok" and l["model"] == "fake-llm"
    assert l["prompt_tokens"] == 18 and l["eval_tokens"] == 70
    assert summarize_llm({})["text"] is None        # no fabricated fields


def test_missing_fields_not_fabricated():
    t = summarize_tev1({"answers": {}})
    assert t["decision"] is None and t["confidence"] is None
    assert t["probabilities"] == [] and t["input_tokens"] is None


def test_format_probabilities():
    t = summarize_tev1(TEV1)
    first = format_probabilities(t["probabilities"]).splitlines()[0].split()
    assert first == ["duplicate_charge", "99.4%"]
    assert format_probabilities([]) == ""           # plan 4.V: empty, not zeros


def test_total_elapsed():
    assert total_elapsed_s(0.82, 4.31) == 5.13
    assert total_elapsed_s(0.82, None) is None      # no fabricated totals


def test_build_comparison():
    c = build_comparison(summarize_tev1(TEV1), summarize_llm(LLM))
    assert c["llm_only"]["response"] == "ok"
    assert c["llm_only"]["response_time_s"] == 4.31
    assert "confidence" not in c["llm_only"]        # spec 16: no LLM confidence, ever
    right = c["tev1_plus_llm"]
    assert right["decision"] == "duplicate_charge"
    assert right["confidence"] == 0.983
    assert right["total_time_s"] == 5.13


def test_score_answer_shape():
    # live-probed score shape, values synthetic
    score_result = {
        "model": "fake-tev1",
        "answers": {"impact": {"type": "score", "score": 2.014,
                               "legend": {"0": "minimal", "1": "minor",
                                          "2": "moderate"},
                               "probabilities": {"2": 0.354, "1": 0.231,
                                                 "0": 0.086},
                               "confidence": 0.081}},
        "elapsed_s": 0.9,
    }
    s = summarize_tev1(score_result)
    assert s["decision"] == "2.01 = moderate"
    assert s["probabilities"][0] == ("moderate", 0.354)