# Phase 4 — Result Processor. Pure functions only: NO network calls, NO imports of
# the service modules (they would pull config/requests in). Tev1's parsed result is a
# dict {"model", "answers", "elapsed_s", "usage"?}; the LLM's is
# {"model", "text", "elapsed_s", "thinking"?, "prompt_tokens"?, "eval_tokens"?, "done_reason"?}.
# Every nullable field stays None — never fabricated (spec section 9).
#
# First Tev1 answer = the primary decision (each mode's question set asks one question,
# e.g. "intent"); extra answers are appended into the display rows (Phase 8 reuses this
# when modes ask multi-question sets).


def _summarize_score(qname: str, answer: dict, hev1_result: dict) -> dict:
    """Score-type answers (probed 2026-10-02): {'type': 'score', 'score': 2.014,
    'legend': {'0': 'minimal', ...}, 'probabilities': {'0': 0.086, ...},
    'confidence': 0.081} — legend/probabilities keyed by 0-based index strings,
    criteria sent as an aligned description array. Decision = real score plus the
    real legend title (both from the response; nothing fabricated)."""
    legend = answer.get("legend") if isinstance(answer.get("legend"), dict) else {}
    rows_raw = answer.get("probabilities")
    rows = sorted(rows_raw.items(), key=lambda kv: kv[1], reverse=True) \
        if isinstance(rows_raw, dict) else []
    score = answer.get("score")
    is_number = isinstance(score, (int, float)) and not isinstance(score, bool)
    index = str(int(score)) if is_number else None
    decision = (
        f"{score:.2f} = {legend[index]}" if is_number and index in legend else
        (f"{score}" if is_number else None)
    )
    usage = hev1_result.get("usage") or {}
    return {
        "question": qname,
        "decision": decision,
        "confidence": answer.get("confidence"),
        "probabilities": [(legend.get(k, k), pct) for k, pct in rows],
        "extra_answers": {},
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "elapsed_s": hev1_result.get("elapsed_s"),
        "model": hev1_result.get("model"),
    }


def summarize_tev1(hev1_result: dict) -> dict:
    """Normalize a raw Tev1 result into display facts: first-answer decision +
    confidence + sorted probability rows + real token/elapsed values only."""
    answers = hev1_result.get("answers") or {}
    first = next(iter(answers.items()), (None, None))
    qname, answer = first
    if not isinstance(answer, dict):
        answer = {}
    if answer.get("type") == "score":  # probed score shape routes here
        return _summarize_score(qname, answer, hev1_result)

    probabilities = answer.get("probabilities")
    rows = (
        sorted(probabilities.items(), key=lambda kv: kv[1], reverse=True)
        if isinstance(probabilities, dict)
        else []
    )
    usage = hev1_result.get("usage") or {}

    return {
        "question": qname,
        "decision": answer.get("choice"),
        "confidence": answer.get("confidence"),
        "probabilities": [(label, pct) for label, pct in rows],
        # question name -> (choice, confidence) for every extra question Tev1 answered
        "extra_answers": {
            name: (a.get("choice"), a.get("confidence"))
            for name, a in answers.items()
            if name != qname and isinstance(a, dict)
        },
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "elapsed_s": hev1_result.get("elapsed_s"),
        "model": hev1_result.get("model"),
    }


def summarize_llm(llm_result: dict) -> dict:
    """Normalize a raw LLM result: text + model + real tokens/elapsed only."""
    return {
        "text": llm_result.get("text"),
        "thinking": llm_result.get("thinking"),
        "model": llm_result.get("model"),
        "prompt_tokens": llm_result.get("prompt_tokens"),
        "eval_tokens": llm_result.get("eval_tokens"),
        "elapsed_s": llm_result.get("elapsed_s"),
    }


def format_probabilities(rows: list) -> str:
    """Tev1 panel probability block; caller prints it verbatim. Empty when no data."""
    return "\n".join(f"{label:>22}  {pct * 100:5.1f}%" for label, pct in rows)


def total_elapsed_s(tev1_elapsed, llm_elapsed):
    """Combined timing (spec section 20) — a number only when both parts are."""
    return (
        round(tev1_elapsed + llm_elapsed, 2)
        if isinstance(tev1_elapsed, (int, float)) and isinstance(llm_elapsed, (int, float))
        else None
    )


def build_comparison(tev1_summary: dict, llm_summary: dict) -> dict:
    """Payload for the Compare Both view (spec section 16): real facts only —
    no LLM confidence score exists, and none is fabricated here."""
    return {
        "llm_only": {
            "response": llm_summary.get("text"),
            "model": llm_summary.get("model"),
            "response_time_s": llm_summary.get("elapsed_s"),
        },
        "tev1_plus_llm": {
            "decision": tev1_summary.get("decision"),
            "confidence": tev1_summary.get("confidence"),
            "probabilities": tev1_summary.get("probabilities"),
            "explanation": llm_summary.get("text"),
            "tev1_time_s": tev1_summary.get("elapsed_s"),
            "llm_time_s": llm_summary.get("elapsed_s"),
            "total_time_s": total_elapsed_s(
                tev1_summary.get("elapsed_s"), llm_summary.get("elapsed_s")
            ),
        },
    }


if __name__ == "__main__":
    # Self-check with explicitly SYNTHETIC test-only dicts (verify 4.V). No network.
    synthetic_tev1 = {
        "model": "fake-tev1",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "duplicate_charge",
                "probabilities": {"card_declined": 0.01, "none": 0.33,
                                  "duplicate_charge": 0.9942, "cancel_subscription": 0.0025},
                "confidence": 0.983,
            },
            "urgency": {"type": "choice", "choice": "medium"},  # sorted rows: intent first
        },
        "elapsed_s": 0.82,
        "usage": {"input_tokens": 164, "output_tokens": 1},
    }
    synthetic_llm = {"text": "ok", "model": "fake-llm", "elapsed_s": 4.31,
                     "prompt_tokens": 18, "eval_tokens": 70}

    t = summarize_tev1(synthetic_tev1)
    assert t["question"] == "intent" and t["decision"] == "duplicate_charge"
    assert t["probabilities"][0] == ("duplicate_charge", 0.9942)          # sorted desc
    assert t["extra_answers"] == {"urgency": ("medium", None)}
    assert t["model"] == "fake-tev1" and t["elapsed_s"] == 0.82

    l = summarize_llm(synthetic_llm)
    assert l["text"] == "ok" and l["prompt_tokens"] == 18

    assert format_probabilities(t["probabilities"]).splitlines()[0].split() == ["duplicate_charge", "99.4%"]

    assert total_elapsed_s(0.82, 4.31) == 5.13
    assert total_elapsed_s(0.82, None) is None                            # no fabricated totals

    c = build_comparison(t, l)
    assert c["tev1_plus_llm"]["decision"] == "duplicate_charge"
    assert c["tev1_plus_llm"]["total_time_s"] == 5.13
    assert "confidence" not in c["llm_only"]                              # spec 16: never fabricated

    empty_tev1 = summarize_tev1({"answers": {}})                          # degraded answers
    assert empty_tev1["decision"] is None and empty_tev1["probabilities"] == []
    assert summarize_llm({})["text"] is None
    assert format_probabilities(summarize_tev1({"answers": {}})["probabilities"]) == ""

    # score-type (real shape captured from a live probe, values SYNTHETIC-test-only)
    synthetic_score = {
        "model": "fake-tev1",
        "answers": {
            "impact": {
                "type": "score", "score": 2.014140444313675,
                "legend": {"0": "minimal", "1": "minor", "2": "moderate",
                           "3": "major", "4": "critical"},
                "probabilities": {"0": 0.086629674771349, "1": 0.23197283239082,
                                  "2": 0.354927389450461, "3": 0.233567580527546,
                                  "4": 0.092902522859823},
                "confidence": 0.081090835762079,
            }
        },
        "elapsed_s": 0.9,
        "usage": {"input_tokens": 156, "output_tokens": 1},
    }
    s = summarize_tev1(synthetic_score)
    assert s["question"] == "impact" and s["model"] == "fake-tev1"
    assert s["decision"] == "2.01 = moderate"                # real score + legend title
    assert s["probabilities"][0][0] == "moderate" and s["probabilities"][0][1] > 0.35
    assert s["input_tokens"] == 156 and s["elapsed_s"] == 0.9

    print("OK")