"""
Retry logic with exponential backoff and graceful degradation.

Delegates all LLM calls to structured_output.classify_with_json_mode so that
LLM wiring stays in one place.

# PRODUCTION NOTE: In a real system, add dead-letter queue support for
# tickets that exhaust all retries, integrate with an alerting system for
# retry storms, and consider circuit-breaker patterns to avoid cascading
# failures during OpenAI outages.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from openai import RateLimitError
from pydantic import ValidationError

from schema import TicketClassification, IssueCategory, TeamOwner, Priority, Sentiment
from production_modules.validate_response import validate_classification
from production_modules.structured_output import (
    classify_with_json_mode,
    SIMPLE_SYSTEM_PROMPT,
)
from production_modules.prompt_versioning import get_active_prompt

load_dotenv()
logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss:120b")

SAFE_CLASSIFICATION = TicketClassification(
    issue_category=IssueCategory.OTHER,
    assigned_team=TeamOwner.CUSTOMER_SUPPORT,
    priority=Priority.MEDIUM,
    user_sentiment=Sentiment.NEUTRAL,
    confidence_score=0.0,
    reasoning="Automatic fallback: classification failed after all retries",
    requires_human_review=True,
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((RateLimitError, ValidationError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def classify_with_retry(ticket_text: str, model: str = _DEFAULT_MODEL) -> TicketClassification:
    """
    Attempt classification via classify_with_json_mode with automatic retry.
    On the first retry, switches to a simpler conservative system prompt.
    """
    attempt = classify_with_retry.statistics.get("attempt_number", 1)

    if attempt > 1:
        logger.warning("Retry attempt %d — switching to simple system prompt", attempt)
        system_prompt = SIMPLE_SYSTEM_PROMPT
    else:
        system_prompt = get_active_prompt()["template"]

    result = classify_with_json_mode(
        ticket_text=ticket_text,
        system_prompt=system_prompt,
        model=model,
    )

    validation = validate_classification(result)
    if not validation.is_valid:
        raise ValidationError.from_exception_data(
            title="TicketClassification",
            input_type="python",
            input=result.model_dump() if result else {},
        )
    return validation.validated_classification


def classify_with_fallback(ticket_text: str, model: str = _DEFAULT_MODEL) -> TicketClassification:
    """Top-level function: tries classify_with_retry, returns SAFE_CLASSIFICATION on total failure."""
    try:
        return classify_with_retry(ticket_text, model)
    except Exception as exc:
        logger.error("All retries exhausted: %s. Returning safe classification.", exc)
        return SAFE_CLASSIFICATION


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ticket = "I cannot log into my account. It keeps saying incorrect password."
    result = classify_with_fallback(ticket)
    print(result.model_dump_json(indent=2))
