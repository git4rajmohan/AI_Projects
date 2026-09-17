"""LLM configuration for Ollama Cloud via ADK's LiteLlm.

Ollama Cloud exposes an OpenAI-compatible endpoint at https://ollama.com/v1.
ADK uses LiteLLM internally, which speaks OpenAI format natively.
No proxy needed — unlike the AI_GraphRAG project which needed a translation proxy.

Environment variables (read by LiteLLM directly):
  OPENAI_API_KEY  — Ollama Cloud API key
  OPENAI_API_BASE — https://ollama.com/v1
"""

from google.adk.models.lite_llm import LiteLlm

from app.core.config import settings


def get_model(model_name: str | None = None, max_tokens: int | None = None) -> LiteLlm:
    """Get a LiteLlm model instance for Ollama Cloud.

    Args:
        model_name: Model name with provider prefix (e.g. "openai/gpt-oss:120b").
                    If None, uses the default from settings.
        max_tokens: Optional output token cap. Reasoning models can burn most of
                    their budget on hidden chain-of-thought before ever emitting
                    the actual answer — raise this for callers (like the Planner)
                    that need room for both reasoning and a large structured output.

    Returns:
        LiteLlm instance configured for Ollama Cloud.

    Environment:
        OPENAI_API_KEY  — set in .env (Ollama Cloud API key)
        OPENAI_API_BASE — set in .env (https://ollama.com/v1)
    """
    model = model_name or settings.llm_model
    # num_retries lets LiteLLM auto-retry transient upstream errors (500s, timeouts,
    # rate limits) with backoff inside a single call, before our own agent-level
    # retry has to redo the whole tool-calling conversation from scratch.
    kwargs: dict = {"num_retries": 3}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return LiteLlm(model=model, **kwargs)


def get_default_model() -> LiteLlm:
    """Get the default LLM model for the platform."""
    return get_model()


def get_fast_model() -> LiteLlm:
    """Get a fast/cheap model for simple tasks."""
    return get_model("openai/gpt-oss:20b")


def get_reasoning_model() -> LiteLlm:
    """Get a high-reasoning model for complex planning."""
    return get_model()  # Uses default (gpt-oss:120b) — can be changed later