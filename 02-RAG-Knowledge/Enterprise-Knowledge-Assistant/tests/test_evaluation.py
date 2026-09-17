"""Offline-evaluation metric + quality-gate tests (items 14–15) — hermetic.

No services needed: every function is pure over plain data. The LLM judge is
covered for parsing/robustness with a fake LLM (monkeypatched), never a live
call — live judge behavior is exercised by scripts/evaluate_rag.py against
real services.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation.metrics import (
    FaithfulnessVerdict,
    citation_correct,
    context_relevant,
    is_refusal,
    judge_faithfulness,
    keyword_correct,
    keyword_matches,
)
from app.evaluation.quality_gates import (
    DEFAULT_THRESHOLDS,
    check_quality_gates,
    compute_overall,
    load_thresholds,
)
from app.evaluation.runner import load_dataset

_ROW = {
    "id": "t-1", "question": "q?", "category": "factual", "difficulty": "easy",
    "expected_answer": "15 days", "expected_source": "pto-and-leave-policy.pdf",
    "expected_source_section": "2.1", "expected_keywords": ["15", "days"],
    "expected_source_any": ["pto-and-leave-policy.pdf"], "expect_refusal": False,
}
_REFUSAL_ROW = {
    "id": "t-2", "question": "jets?", "category": "unsupported", "difficulty": "medium",
    "expected_answer": "REFUSE", "expected_source": None,
    "expected_source_section": None, "expected_keywords": [],
    "expected_source_any": [], "expect_refusal": True,
}


# -- mechanical metrics ---------------------------------------------------- #
def test_is_refusal_matches_gate_and_llm_phrases() -> None:
    assert is_refusal("I don't have enough evidence in the provided documents to answer.")
    assert is_refusal("The information could not be found in the available documents.")
    assert not is_refusal("Employees receive 15 days of annual leave.")


def test_keyword_matches_case_insensitive() -> None:
    hits = keyword_matches("Employees get 15 DAYS of PTO", ["15", "days", "pto"])
    assert hits == ["15", "days", "pto"]


def test_keyword_correct_respects_min_matches() -> None:
    row = {**_ROW, "expected_keywords": ["15", "20", "25", "30"], "min_keyword_matches": 2}
    assert keyword_correct(row, "You get 15 or 20 days depending on tenure")
    assert not keyword_correct(row, "You get 15 days")


def test_citation_correct_with_expected_source() -> None:
    assert citation_correct(_ROW, ["pto-and-leave-policy.pdf", "holiday-schedule.pdf"])
    assert not citation_correct(_ROW, ["benefits-overview.pdf"])
    # Refusal rows pass trivially.
    assert citation_correct(_REFUSAL_ROW, [])


def test_context_relevant() -> None:
    assert context_relevant(_ROW, "[1] PTO accrual: 15 days for 0-2 years")
    assert not context_relevant(_ROW, "[1] Security policy: MFA required")


# -- faithfulness judge (fake LLM, no services) ---------------------------- #
class _FakeLLM:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    def complete(self, prompt: str) -> str:
        return self._raw


def _judge_with(monkeypatch: pytest.MonkeyPatch, raw: str) -> FaithfulnessVerdict:
    from app.llm import ollama_manager

    class _FakeManager:
        def get_llm(self) -> _FakeLLM:
            return _FakeLLM(raw)

    monkeypatch.setattr(ollama_manager, "get_llm_manager", lambda settings=None: _FakeManager())
    return judge_faithfulness("evidence text", "answer text")


def test_judge_parses_clean_json(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = _judge_with(
        monkeypatch, '{"faithful": true, "unsupported_claims": []}'
    )
    assert verdict.faithful is True and not verdict.unsupported_claims


def test_judge_parses_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = _judge_with(
        monkeypatch, '```json\n{"faithful": false, "unsupported_claims": ["made-up number"]}\n```'
    )
    assert verdict.faithful is False
    assert verdict.unsupported_claims == ["made-up number"]


def test_judge_regex_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = _judge_with(monkeypatch, 'blah blah "faithful": true, ...')
    assert verdict.faithful is True


def test_judge_unparseable_is_error_not_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = _judge_with(monkeypatch, "I cannot evaluate this.")
    assert verdict.faithful is False
    assert verdict.judge_error is not None and "unparseable" in verdict.judge_error


def test_judge_service_down_is_error_not_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import ollama_manager

    class _BrokenManager:
        def get_llm(self) -> object:
            raise ConnectionError("cloud down")

    monkeypatch.setattr(ollama_manager, "get_llm_manager", lambda settings=None: _BrokenManager())
    verdict = judge_faithfulness("evidence", "answer")
    assert verdict.judge_error is not None
    assert "cloud down" in verdict.judge_error


def test_strip_citation_lines_keeps_claims_drops_sources() -> None:
    from app.evaluation.metrics import _strip_citation_lines

    answer = (
        "Full-time employees are entitled to 10 sick days per calendar year.\n"
        "Sources: [2] (Acme Corp policy)\n"
        "[1] pto-and-leave-policy.pdf\n"
        "[G1] knowledge graph"
    )
    stripped = _strip_citation_lines(answer)
    assert "10 sick days" in stripped
    assert "Sources:" not in stripped
    assert "pto-and-leave-policy.pdf" not in stripped
    assert "knowledge graph" not in stripped


# -- dataset + gates ------------------------------------------------------- #
def test_runner_loads_real_dataset() -> None:
    rows = load_dataset()
    assert len(rows) >= 50


def test_load_thresholds_defaults_match_spec() -> None:
    thresholds = load_thresholds(Path("nonexistent.yaml"))
    assert thresholds["faithfulness"] == 0.85
    assert thresholds["refusal_accuracy"] == 1.00
    assert thresholds == DEFAULT_THRESHOLDS


def test_load_thresholds_yaml_override(tmp_path: Path) -> None:
    cfg = tmp_path / "gates.yaml"
    cfg.write_text("quality_gates:\n  faithfulness: 0.99\n", encoding="utf-8")
    thresholds = load_thresholds(cfg)
    assert thresholds["faithfulness"] == 0.99
    assert thresholds["refusal_accuracy"] == 1.00  # untouched keys keep defaults


def _make_result(**overrides: object) -> object:
    from app.evaluation.metrics import QuestionResult

    base = dict(
        id="t-1", question="q", category="factual", difficulty="easy",
        answer="15 days", expected_answer="15 days", refused=False, gate_refused=False,
        citations=["pto-and-leave-policy.pdf"], retrieved_chunk_ids=["c1"],
        contributed_by=[["vector", "bm25"]], context="PTO 15 days",
        refusal_correct=True, citation_correct=True, keyword_correct=True,
        context_relevant=True, keyword_hits=["15"], latency_s=2.0,
        faithful=True, unsupported_claims=[], judge_error=None,
        passed=True, failure_reasons=[],
    )
    base.update(overrides)
    return QuestionResult(**base)  # type: ignore[arg-type]


def test_check_quality_gates_passes_on_perfect_results() -> None:
    results = [_make_result() for _ in range(4)]
    report = check_quality_gates(results, dict(DEFAULT_THRESHOLDS))
    assert report["passed"] is True
    assert report["gate_failures"] == []


def test_check_quality_gates_fails_low_faithfulness() -> None:
    results = [_make_result() for _ in range(4)]
    results[0].faithful = False  # 3/4 = 0.75 < 0.85
    results[0].passed = False
    results[0].failure_reasons = ["unfaithful"]
    report = check_quality_gates(results, dict(DEFAULT_THRESHOLDS))
    assert report["passed"] is False
    assert any(f["metric"] == "faithfulness" for f in report["gate_failures"])


def test_check_quality_gates_fails_refusal_accuracy() -> None:
    results = [_make_result(), _make_result(id="t-2", refused=True, refusal_correct=False,
                                            passed=False, failure_reasons=["refusal mismatch"])]
    report = check_quality_gates(results, dict(DEFAULT_THRESHOLDS))
    assert report["passed"] is False
    assert any(f["metric"] == "refusal_accuracy" for f in report["gate_failures"])


def test_compute_overall_excludes_judge_errors() -> None:
    results = [
        _make_result(faithful=True),
        _make_result(id="t-2", faithful=None, judge_error="judge down", passed=True),
    ]
    overall = compute_overall(results)  # type: ignore[arg-type]
    assert overall["judged_questions"] == 1
    assert overall["faithfulness"] == 1.0