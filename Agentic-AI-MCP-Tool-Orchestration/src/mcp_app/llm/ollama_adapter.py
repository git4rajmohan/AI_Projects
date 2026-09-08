"""Ollama HTTP adapter with timeout and structured error handling."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from mcp_app.config.schema import AppSettings
from mcp_app.core.errors import LLMConnectionError, LLMTimeoutError
from mcp_app.observability.logger import get_logger

log = get_logger(__name__)


class OllamaResponse:
    """Parsed response from Ollama /api/chat endpoint."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    @property
    def message(self) -> dict[str, Any]:
        return self._raw.get("message", {})

    @property
    def content(self) -> str:
        return self.message.get("content", "")

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return self.message.get("tool_calls") or []

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def model(self) -> str:
        return self._raw.get("model", "")

    @property
    def done(self) -> bool:
        return bool(self._raw.get("done", True))


class OllamaAdapter:
    """
    Async Ollama /api/chat client.

    Handles:
      - Timeouts (llm_seconds from settings)
      - Connection errors → LLMConnectionError
      - Timeout errors → LLMTimeoutError
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._base_url = settings.ollama.host.rstrip("/")
        self._model = settings.ollama.model
        self._temperature = settings.ollama.temperature
        self._num_ctx = settings.ollama.num_ctx
        self._timeout = float(settings.timeouts.llm_seconds)
        # ponytail: only send the header when a key exists — local Ollama sends none
        self._headers = (
            {"Authorization": f"Bearer {settings.ollama.api_key}"}
            if settings.ollama.api_key else {}
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        stream: bool = False,
    ) -> OllamaResponse:
        """
        Call Ollama /api/chat.

        Args:
            messages: OpenAI-style message list.
            tools:    Optional list of tool schemas in Ollama function format.
            stream:   If True uses streaming (not supported here, raises).

        Returns:
            OllamaResponse wrapping the response dict.

        Raises:
            LLMConnectionError: Cannot reach Ollama.
            LLMTimeoutError:    Request exceeded llm_seconds.
        """
        if stream:
            raise NotImplementedError("Streaming is not yet implemented.")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_ctx": self._num_ctx,
            },
        }
        if tools:
            payload["tools"] = tools

        log.debug(
            "Ollama request: model=%s, %d messages, %d tools",
            self._model, len(messages), len(tools or []),
        )

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers=self._headers,
            ) as client:
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama request timed out after {self._timeout}s. "
                "Increase timeouts.llm_seconds in app_settings.yaml."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Make sure Ollama is running: `ollama serve`."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMConnectionError(
                f"Ollama returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ) from exc

        log.debug(
            "Ollama response: model=%s, tool_calls=%d",
            data.get("model"), len(data.get("message", {}).get("tool_calls") or []),
        )
        return OllamaResponse(data)

    async def check_connection(self) -> bool:
        """Return True if Ollama is reachable, False otherwise."""
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=5.0, headers=self._headers
            ) as client:
                resp = await client.get("/api/tags")
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False
