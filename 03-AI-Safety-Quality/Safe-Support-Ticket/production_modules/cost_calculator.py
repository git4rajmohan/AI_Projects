"""
Token cost calculation and session-level cost tracking.

# PRODUCTION NOTE: In a real system, persist cost data to a database per
# user/org/request, set up budget alerts, expose a cost dashboard, and
# integrate with billing systems. For metered providers, reconcile totals
# against the provider's usage/billing API.

# COSTING MODEL FOR OLLAMA CLOUD: Ollama Cloud bills via subscription plans
# (GPU-minutes), not per token, so there is no public per-token price list.
# This module therefore tracks token counts as telemetry and applies USD
# rates only when they are configured (see OLLAMA_*_PRICE_PER_1K below).
# With defaults, costs report $0.00 while token usage remains fully visible.
"""

import logging
import os
import tiktoken
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Prices in USD per 1,000 tokens (as of 2024)
PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.00060},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4-turbo": {"input": 0.010, "output": 0.030},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}

# Env-driven reference rates (USD per 1K tokens). Defaults are 0.0 because
# Ollama Cloud bills via subscription rather than per token. Set these in
# .env to model an equivalent metered price if/when one applies.
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss:120b")
_OLLAMA_INPUT_PRICE = float(os.getenv("OLLAMA_INPUT_PRICE_PER_1K", "0.0"))
_OLLAMA_OUTPUT_PRICE = float(os.getenv("OLLAMA_OUTPUT_PRICE_PER_1K", "0.0"))

# Model name prefixes served by Ollama Cloud — rates resolve from env at call time.
OLLAMA_MODEL_PREFIXES = (
    "gpt-oss", "qwen", "glm", "kimi", "deepseek", "llama", "mistral", "phi",
)


def _pricing_for(model: str) -> dict[str, float]:
    """Resolve per-1K pricing for a model.

    Env-configured rates apply to Ollama-hosted model names; the static
    table is a fallback for legacy OpenAI model names.
    """
    if any(model.startswith(prefix) for prefix in OLLAMA_MODEL_PREFIXES):
        return {"input": _OLLAMA_INPUT_PRICE, "output": _OLLAMA_OUTPUT_PRICE}
    return PRICING.get(model, {"input": 0.0, "output": 0.0})


@dataclass
class CostInfo:
    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float


class SessionCostTracker:
    """Accumulates cost across multiple LLM calls in a session."""

    def __init__(self):
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._call_count: int = 0

    def record(self, cost_info: CostInfo) -> None:
        self._total_input_tokens += cost_info.input_tokens
        self._total_output_tokens += cost_info.output_tokens
        self._total_cost_usd += cost_info.total_cost_usd
        self._call_count += 1

    @property
    def summary(self) -> dict:
        return {
            "calls": self._call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": round(self._total_cost_usd, 6),
        }


# Module-level session tracker (reset per process)
session_tracker = SessionCostTracker()


def count_tokens(text: str, model: str = DEFAULT_OLLAMA_MODEL) -> int:
    """Count tokens in a string using tiktoken.

    Falls back to the cl100k_base BPE for models tiktoken does not know
    (e.g. Ollama-hosted models such as gpt-oss:120b). The estimate is close
    for GPT-family tokenisers; treat counts for other families as approximate.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    record_to_session: bool = True,
) -> CostInfo:
    """Calculate cost for an LLM call and optionally record to session tracker."""
    pricing = _pricing_for(model)
    if pricing == {"input": 0.0, "output": 0.0}:
        logger.warning(
            "No pricing found for model '%s' — applying $0.00 rates. "
            "Set OLLAMA_INPUT_PRICE_PER_1K / OLLAMA_OUTPUT_PRICE_PER_1K to track USD cost.",
            model,
        )

    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    total = input_cost + output_cost

    info = CostInfo(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=round(input_cost, 6),
        output_cost_usd=round(output_cost, 6),
        total_cost_usd=round(total, 6),
    )

    if record_to_session:
        session_tracker.record(info)

    return info


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prompt = "Classify this ticket: My order hasn't arrived after 2 weeks!"
    response = '{"issue_category": "delivery_issue", "priority": "high"}'

    in_tokens = count_tokens(prompt)
    out_tokens = count_tokens(response)
    cost = calculate_cost(DEFAULT_OLLAMA_MODEL, in_tokens, out_tokens)

    print(f"Model        : {cost.model}")
    print(f"Input tokens : {cost.input_tokens}")
    print(f"Output tokens: {cost.output_tokens}")
    print(f"Input cost   : ${cost.input_cost_usd:.6f}")
    print(f"Output cost  : ${cost.output_cost_usd:.6f}")
    print(f"Total cost   : ${cost.total_cost_usd:.6f}")
    print(f"Session total: {session_tracker.summary}")
