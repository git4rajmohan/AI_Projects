"""
LLM response validation using Pydantic.

# PRODUCTION NOTE: In a real system, add custom business-rule validators
# (e.g., CRITICAL priority must always require_human_review), log validation
# failures to a monitoring system (Datadog, Sentry), and alert on high
# failure rates which could indicate a model degradation event.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from pydantic import ValidationError
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schema import TicketClassification


@dataclass
class ValidationResult:
    is_valid: bool
    validated_classification: Optional[TicketClassification] = None
    error_details: list[str] = field(default_factory=list)


def validate_classification(raw: Any) -> ValidationResult:
    """
    Validate LLM output against TicketClassification schema.
    Accepts a dict, a TicketClassification instance, or any JSON-serializable object.
    """
    errors: list[str] = []

    # Already a valid instance — re-validate to catch edge cases
    if isinstance(raw, TicketClassification):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = raw
    else:
        return ValidationResult(
            is_valid=False,
            error_details=[f"Unexpected type: {type(raw).__name__}"],
        )

    # Pydantic structural validation
    try:
        classification = TicketClassification.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            errors.append(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")
        return ValidationResult(is_valid=False, error_details=errors)

    # Extra business-rule checks beyond Pydantic constraints
    if not (0.0 <= classification.confidence_score <= 1.0):
        errors.append(f"confidence_score {classification.confidence_score} out of range [0, 1]")

    if classification.confidence_score < 0.5 and not classification.requires_human_review:
        errors.append("Low confidence score should set requires_human_review=True")

    if errors:
        return ValidationResult(is_valid=False, error_details=errors)

    return ValidationResult(is_valid=True, validated_classification=classification)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    good = {
        "issue_category": "payment_issue",
        "assigned_team": "payments_team",
        "priority": "high",
        "user_sentiment": "angry",
        "confidence_score": 0.95,
        "reasoning": "Customer reports duplicate charge",
        "requires_human_review": False,
    }
    bad = {
        "issue_category": "invalid_category",
        "assigned_team": "payments_team",
        "priority": "urgent",   # not a valid Priority enum value
        "user_sentiment": "angry",
        "confidence_score": 1.5,   # out of range
        "reasoning": "",
        "requires_human_review": False,
    }

    for label, data in [("VALID", good), ("INVALID", bad)]:
        result = validate_classification(data)
        print(f"[{label}] is_valid={result.is_valid}")
        if result.error_details:
            for e in result.error_details:
                print(f"  - {e}")
