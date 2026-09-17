"""Local Ollama daemon provider (plan.md Phase 7)."""

from __future__ import annotations

from typing import Any

from llama_index.llms.ollama import Ollama

from app.llm.providers.base import LLMProvider


class LocalOllamaProvider(LLMProvider):
    """LLM + embeddings from the local Ollama daemon (no auth)."""

    def get_llm(self) -> Any:
        return Ollama(
            model=self.settings.llm_model,
            base_url=self.settings.local_base_url,
            request_timeout=120,
        )