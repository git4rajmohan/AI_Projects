"""Thin provider factory (plan.md Phase 7).

Reads ``OLLAMA_PROVIDER`` from Settings and returns the selected
:class:`LLMProvider`. No other module is allowed to branch on local/cloud.
"""

from __future__ import annotations

from functools import lru_cache

from app.config.settings import Settings, get_settings
from app.llm.providers.base import LLMProvider, build_provider


@lru_cache(maxsize=1)
def _cached_provider(settings: Settings) -> LLMProvider:
    return build_provider(settings)


def get_llm_manager(settings: Settings | None = None) -> LLMProvider:
    """The selected provider instance (cached — construction is cheap but
    the underlying client objects should be reused across queries)."""
    return _cached_provider(settings or get_settings())