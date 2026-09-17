"""Evidence-sufficiency gate — refuse BEFORE calling the LLM (§11).

"Grounded because the prompt says so" is not grounding. This gate makes the
refusal *mechanical*: when retrieved evidence doesn't clear the sufficiency
bar, the engine returns a refusal without ever invoking the LLM, so no
hallucinated answer can be produced for unrelated questions.

Threshold calibration (scripts/probe_scores.py, 2026-09-09, real corpus):

    known   questions  best cosine score: 0.627–0.737  (6 queries)
    unknown questions  best cosine score: 0.453–0.638  (5 queries)

    0.55 separates all genuinely-unrelated queries (World Cup, cookie recipe,
    Tesla pricing, Louvre hours ≤ 0.53) from all answerable ones (≥ 0.63).

Two known boundary cases, deliberately handled differently:

  * "private jet travel policy" scores 0.638 — it lexically overlaps real
    travel-reimbursement policy text, so it sits ABOVE the gate. It is caught
    by the second layer: the §25 grounded prompt instructs the LLM to answer
    "not found" when the context doesn't answer the question, and the §47
    tests assert that behavior. The gate handles the mechanical case; the
    prompt handles the semantic case. Both layers are tested.
  * genuinely low-evidence states (gate refusal) never reach the LLM, so the
    §47 unknown-question LLM layer only ever sees plausible-but-unrelated
    context — the harder, more interesting case.

The threshold is configurable via EVIDENCE_MIN_SCORE (default 0.55).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

#: Default below the calibrated minimum known-question score (0.627) and above
#: the maximum genuinely-unrelated score (0.53). Settable via EVIDENCE_MIN_SCORE.
DEFAULT_MIN_SCORE = 0.55

#: Standard refusal text (§11 example behavior). Returned verbatim by the
#: engine when the gate fires — the LLM is never called.
REFUSAL_MESSAGE = (
    "I don't have enough evidence in the provided documents "
    "to answer this question reliably."
)


def _min_score(settings: Settings) -> float:
    """Configured threshold (env override), falling back to the calibrated default."""
    raw = os.environ.get("EVIDENCE_MIN_SCORE", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning("EVIDENCE_MIN_SCORE=%r is not a float; using %s", raw, DEFAULT_MIN_SCORE)
    return DEFAULT_MIN_SCORE


@dataclass
class GateDecision:
    """Outcome of the evidence-sufficiency check — kept for observability."""

    allowed: bool
    best_score: float
    threshold: float
    reason: str


class EvidenceGate:
    """Pre-LLM refusal: blocks answers that lack sufficient retrieved evidence.

    Vector hits carry real cosine similarity scores from Qdrant; the gate
    refuses when the best score is below the calibrated threshold. Graph
    triplets don't carry comparable scores, so they never *enable* an answer
    by themselves — but they cannot rescue unrelated-vector queries either,
    because unrelated queries produce unrelated triplets; refusing on vector
    score alone is the conservative, correct behavior.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.threshold = _min_score(self.settings)

    def check(self, best_vector_score: float | None) -> GateDecision:
        """Allow generation only when evidence exists and clears the bar."""
        if best_vector_score is None:
            return GateDecision(
                allowed=False,
                best_score=0.0,
                threshold=self.threshold,
                reason="no vector evidence retrieved",
            )
        if best_vector_score < self.threshold:
            return GateDecision(
                allowed=False,
                best_score=best_vector_score,
                threshold=self.threshold,
                reason=(
                    f"best evidence score {best_vector_score:.3f} is below the "
                    f"sufficiency threshold {self.threshold:.3f}"
                ),
            )
        return GateDecision(
            allowed=True,
            best_score=best_vector_score,
            threshold=self.threshold,
            reason="sufficient evidence",
        )