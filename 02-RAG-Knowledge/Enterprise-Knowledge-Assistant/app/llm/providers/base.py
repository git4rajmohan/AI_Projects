"""LLMProvider interface (plan.md Phase 7).

Two implementations exist: :class:`LocalOllamaProvider` (local daemon, no auth)
and :class:`OllamaCloudProvider` (Ollama Cloud, bearer-token auth). The rest of
the application only ever sees this interface — provider selection lives in
``app/llm/ollama_manager.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.config.settings import Settings


class LLMProvider(ABC):
    """Uniform access to LLM + embedding model, regardless of local/cloud."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def get_llm(self) -> Any:
        """Return a LlamaIndex ``LLM`` for chat/completion."""

    def get_embedding_model(self) -> Any:
        """Embeddings always run on the LOCAL daemon (the cloud plan has no
        embedding models), so every provider shares this implementation."""
        from llama_index.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(
            model_name=self.settings.embed_model,
            base_url=self.settings.local_base_url,
        )


def build_provider(settings: Settings) -> LLMProvider:
    """Select the provider named by ``OLLAMA_PROVIDER`` (the one factory branch)."""
    if settings.provider == "cloud":
        from app.llm.providers.ollama_cloud_provider import OllamaCloudProvider

        return OllamaCloudProvider(settings)
    from app.llm.providers.local_ollama_provider import LocalOllamaProvider

    return LocalOllamaProvider(settings)