"""Ollama Cloud LLM client and return-reason classifier (Phase 5).

Uses ``langchain_ollama.ChatOllama`` pointed at Ollama Cloud with Bearer auth
passed through ``client_kwargs={"headers": {...}}`` (verified against
langchain-ollama 1.1.0 — there is no dedicated ``headers`` field).

Structured output strategy (verified live against ``gpt-oss:120b`` on Ollama
Cloud): ``ChatOllama(format=<json-schema>)`` with a single-enum-property
object schema makes the model return the bare enum string
(``"damaged_defective"`` | ``"buyer_remorse"``). Note that
``.with_structured_output()`` does NOT work with this model/endpoint (the
JSON parser rejects the bare string), so we use the explicit ``format``
schema plus a tolerant parser instead.

Failure handling never breaks a run: any LLM/parse failure falls back to the
deterministic keyword classifier from Phase 3 (``_fallback_classify``).
"""
import logging
from typing import Optional, Tuple

from langchain_ollama import ChatOllama

from app.config import settings
from app.schemas import ItemCondition

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schema constraining the model's classification output
# ---------------------------------------------------------------------------
CONDITION_ENUM = [ItemCondition.damaged_defective.value, ItemCondition.buyer_remorse.value]

CLASSIFICATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "condition": {
            "type": "string",
            "enum": CONDITION_ENUM,
        }
    },
    "required": ["condition"],
}

CLASSIFY_SYSTEM_PROMPT = (
    "You classify e-commerce return reasons. Choose exactly one condition: "
    '"damaged_defective" when the item is broken, defective, damaged, or '
    'malfunctioning; "buyer_remorse" for any other reason (changed mind, '
    "wrong size/color, no longer needed). Respond with only the condition string."
)


def build_chat_model() -> "ChatOllama":
    """Build a ``ChatOllama`` client for Ollama Cloud.

    Auth: ``OLLAMA_API_KEY`` as a Bearer header via ``client_kwargs`` (the
    verified mechanism for langchain-ollama 1.1.0 cloud usage).
    """
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        client_kwargs={
            "headers": {"Authorization": f"Bearer {settings.OLLAMA_API_KEY}"}
        },
        temperature=0,
        format=CLASSIFICATION_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Parsing / fallback
# ---------------------------------------------------------------------------
def parse_condition(raw: object) -> ItemCondition:
    """Map an LLM response to an :class:`ItemCondition` or raise ``ValueError``.

    Accepts the bare enum string, a JSON object string
    (``{"condition": "..."}``), or either with surrounding whitespace/quotes.
    """
    text = str(raw or "").strip()
    # Direct enum match
    for value in CONDITION_ENUM:
        if value in text:
            return ItemCondition(value)
    raise ValueError(f"unparseable classification output: {raw!r}")


def _fallback_classify(reason_text: str) -> ItemCondition:
    """Deterministic keyword classifier — last-resort fallback for Phase 5."""
    from app.graph import classify_condition_stub

    return classify_condition_stub(reason_text)


def classify_reason_with_source(reason_text: str) -> Tuple[ItemCondition, str]:
    """Classify a free-text return reason via the LLM, with keyword fallback.

    Returns ``(condition, classifier)`` where *classifier* is ``"llm"`` when
    Ollama Cloud produced the label, or ``"fallback"`` when the deterministic
    keyword classifier was used instead.

    Never raises: LLM errors, empty/None API keys, and unparseable outputs
    all fall back to ``_fallback_classify`` and log a warning.
    """
    if not settings.OLLAMA_API_KEY:
        logger.warning("OLLAMA_API_KEY not set — using keyword fallback classifier")
        return _fallback_classify(reason_text), "fallback"

    try:
        llm = build_chat_model()
        response = llm.invoke(
            [
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": f"Reason: {reason_text}"},
            ]
        )
        return parse_condition(response.content), "llm"
    except Exception as exc:  # noqa: BLE001 — fallback must swallow everything
        logger.warning("LLM classification failed (%s) — using keyword fallback", exc)
        return _fallback_classify(reason_text), "fallback"


def classify_reason(reason_text: str) -> ItemCondition:
    """Condition-only wrapper around :func:`classify_reason_with_source`."""
    condition, _ = classify_reason_with_source(reason_text)
    return condition