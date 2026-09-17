"""Ollama Cloud provider (plan.md Phase 7).

Verified against llama-index-llms-ollama 0.11.0: the built-in ``Ollama`` class
forwards a ``headers`` dict to the underlying ``ollama.Client`` and speaks the
native Ollama format, so pointing it at ``https://ollama.com`` with a
``Authorization: Bearer <key>`` header works for both ``complete()`` and
``chat()`` — no ``CustomLLM`` subclass needed.

Embeddings still come from the LOCAL daemon (the cloud plan has no embedding
models), so this class overrides only ``get_llm``.
"""

from __future__ import annotations

from typing import Any

from llama_index.llms.ollama import Ollama

from app.llm.providers.base import LLMProvider


class OllamaCloudProvider(LLMProvider):
    """Chat LLM from Ollama Cloud (native format + bearer key); embeddings local."""

    def get_llm(self) -> Any:
        # Settings default ends in /api (native surface); the ollama client
        # itself wants the bare host — strip a trailing /api if present.
        # ponytail: same /api-strip as cognee_manager._llm_endpoint; revisit if
        # the client ever wants the full native path.
        host = self.settings.cloud_base_url.rstrip("/")
        if host.endswith("/api"):
            host = host[: -len("/api")]
        return Ollama(
            model=self.settings.llm_model,
            base_url=host,
            headers={"Authorization": f"Bearer {self.settings.api_key}"},
            request_timeout=120,
        )