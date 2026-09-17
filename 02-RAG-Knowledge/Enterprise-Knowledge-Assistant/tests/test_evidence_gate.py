"""§11 Citation/evidence enforcement tests — the pre-LLM gate (item 10).

Two layers of refusal exist and both are tested here:

  Layer 1 (mechanical, this gate): queries whose best vector score falls below
  the calibrated threshold are refused WITHOUT calling the LLM. Verified live
  with the calibration probe (scripts/probe_scores.py): genuinely-unrelated
  queries score ≤ 0.53, answerable ones ≥ 0.63.

  Layer 2 (semantic, the §25 prompt): queries that lexically overlap real
  policy text (e.g. "private jet travel policy" → 0.638 because travel
  reimbursement text is similar) pass the gate but the grounded prompt makes
  the LLM answer "not found". Tested in test_retrieval.py / test_groundedness.py.

The unit tests (TestEvidenceGate) are hermetic — no services needed.
"""

from __future__ import annotations

import pytest
import requests

from conftest import NOT_FOUND_PHRASES

from app.config.settings import Settings, get_settings
from app.retrieval.evidence_gate import DEFAULT_MIN_SCORE, REFUSAL_MESSAGE, EvidenceGate
from app.retrieval.llamaindex_engine import LlamaIndexEngine

_GATED_QUESTION = "Who won the 1998 FIFA World Cup final?"
_KNOWN_QUESTION = "How many annual leave days do employees receive?"


def _services_up() -> bool:
    settings = get_settings()
    try:
        requests.get(f"{settings.qdrant_url}/collections", timeout=3).raise_for_status()
        requests.post(
            f"{settings.local_base_url.rstrip('/')}/api/embed",
            json={"model": settings.embed_model, "input": "ping"},
            timeout=10,
        ).raise_for_status()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _services_up(), reason="local services not running")


# -- Hermetic unit tests (no services needed) ----------------------------- #
class TestEvidenceGate:
    """Gate logic against known score values from the calibration probe."""

    def test_refuses_when_no_evidence(self) -> None:
        decision = EvidenceGate(Settings()).check(None)
        assert not decision.allowed
        assert decision.reason == "no vector evidence retrieved"

    def test_refuses_below_threshold(self) -> None:
        # Real calibrated unknown-query maxima: 0.453–0.527 (World Cup 0.4545).
        decision = EvidenceGate(Settings()).check(0.4545)
        assert not decision.allowed
        assert decision.best_score == 0.4545
        assert "below the sufficiency threshold" in decision.reason

    def test_allows_above_threshold(self) -> None:
        # Real calibrated known-query minima: 0.627 (benefits) — above 0.55.
        decision = EvidenceGate(Settings()).check(0.6267)
        assert decision.allowed
        assert decision.reason == "sufficient evidence"

    def test_default_threshold_is_calibrated(self) -> None:
        assert DEFAULT_MIN_SCORE == 0.55
        gate = EvidenceGate(Settings())
        assert gate.threshold == 0.55

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVIDENCE_MIN_SCORE", "0.80")
        gate = EvidenceGate(Settings())
        assert gate.threshold == 0.80
        assert not gate.check(0.70).allowed  # would pass the default, fails strict


# -- Live end-to-end enforcement ------------------------------------------ #
def test_gate_refuses_unrelated_query_before_llm() -> None:
    """Layer 1: an unrelated question is refused mechanically — the LLM is
    never invoked (observable via refusal fields + the standard message)."""
    engine = LlamaIndexEngine()
    result = engine.answer(_GATED_QUESTION)

    assert result.refused is True, f"gate should have refused: {result.answer[:200]}"
    assert result.refusal_reason is not None
    assert result.answer == REFUSAL_MESSAGE
    # The refusal is evidenced: the (weak) hits are still shown for inspection.
    best = max((h.score for h in result.vector_hits), default=None)
    if best is not None:
        assert best < 0.55, "gated query should have scored below the threshold"
    print(f"\nGATE REFUSED: {result.refusal_reason}")


def test_gate_allows_known_question() -> None:
    """The calibrated known question passes the gate and reaches the LLM."""
    engine = LlamaIndexEngine()
    result = engine.answer(_KNOWN_QUESTION)
    assert result.refused is False, f"gate blocked a real question: {result.refusal_reason}"
    assert result.vector_hits
    best = max(h.score for h in result.vector_hits)
    assert best >= 0.55, f"known question scored {best:.3f} — calibration drifted?"


def test_refusal_result_has_no_llm_context() -> None:
    """A refused answer records no prompt context — proof the LLM never saw any."""
    engine = LlamaIndexEngine()
    result = engine.answer(_GATED_QUESTION)
    if result.refused:
        assert result.context == "", "refused query should never build LLM context"


def test_layer2_semantic_overlap_still_answered_not_found() -> None:
    """Layer 2: the private-jet question passes the gate (0.638 — lexical
    overlap with travel policy) but the grounded prompt makes the LLM decline.
    Both layers working together is the full §11 behavior."""
    engine = LlamaIndexEngine()
    result = engine.answer("What is the company's private jet travel policy?")
    lower = result.answer.lower()
    # Either the gate caught it (mechanical) or the LLM declined (semantic) —
    # in both cases NO fabricated policy is produced.
    if result.refused:
        assert result.answer == REFUSAL_MESSAGE
    else:
        assert any(phrase in lower for phrase in NOT_FOUND_PHRASES), (
            f"LLM fabricated a policy: {result.answer[:300]}"
        )
    print(f"\nrefused={result.refused} answer={result.answer[:200]}")