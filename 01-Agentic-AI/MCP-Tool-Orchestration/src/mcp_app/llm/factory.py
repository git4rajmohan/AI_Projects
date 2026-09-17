"""Factory: create the correct LLM adapter from AppSettings."""
from __future__ import annotations

from typing import Union

from mcp_app.config.schema import AppSettings
from mcp_app.llm.ollama_adapter import OllamaAdapter
from mcp_app.llm.openai_compat_adapter import OpenAICompatAdapter

LLMAdapter = Union[OllamaAdapter, OpenAICompatAdapter]


def create_llm_adapter(settings: AppSettings) -> LLMAdapter:
    """Return the appropriate LLM adapter based on settings.llm_provider."""
    if settings.llm_provider == "openai_compat":
        return OpenAICompatAdapter(settings)
    return OllamaAdapter(settings)
