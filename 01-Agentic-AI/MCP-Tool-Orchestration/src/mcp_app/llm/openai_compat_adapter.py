"""OpenAI-compatible HTTP adapter (OpenAI, Azure OpenAI, Groq, Ollama /v1, etc.)."""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import httpx

from mcp_app.config.schema import AppSettings
from mcp_app.core.errors import LLMConnectionError, LLMTimeoutError
from mcp_app.llm.ollama_adapter import OllamaResponse
from mcp_app.observability.logger import get_logger

log = get_logger(__name__)

# Endpoint suffixes users should NOT include in the base URL — strip them automatically
_ENDPOINT_SUFFIXES = ("/chat/completions", "/completions", "/v1/chat/completions")


def _normalize_base_url(url: str) -> str:
    """Strip known endpoint path suffixes so base_url is always a root/version prefix."""
    url = url.rstrip("/")
    for suffix in _ENDPOINT_SUFFIXES:
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    return url


def _normalize_to_ollama_response(raw_openai: dict[str, Any]) -> dict[str, Any]:
    """
    Convert an OpenAI /v1/chat/completions response dict to the same shape
    as an Ollama /api/chat response.  OllamaResponse + all existing parsers
    work without modification.

    OpenAI shape:
      {
        "model": "...",
        "choices": [{"message": {"role": "assistant", "content": "...",
                                 "tool_calls": [...]}}]
      }

    Ollama shape:
      {
        "model": "...",
        "message": {"role": "assistant", "content": "...", "tool_calls": [...]},
        "done": true
      }

    Tool-call argument normalization: OpenAI encodes arguments as a JSON
    string; Ollama uses a plain dict.  We decode the string here so the
    existing parse_tool_calls() works transparently.
    """
    model = raw_openai.get("model", "")
    choices = raw_openai.get("choices", [])
    if not choices:
        return {"model": model, "message": {"role": "assistant", "content": ""}, "done": True}

    msg = choices[0].get("message", {})
    content = msg.get("content") or ""

    # Strip MiniMax (and similar) proprietary XML that leaks into the content field.
    # e.g. <invoke name="...">...</invoke> and </minimax:tool_call> remnants
    import re as _re
    content = _re.sub(r'<invoke\b[^>]*>.*?</invoke>', '', content, flags=_re.DOTALL)
    content = _re.sub(r'</minimax:\w+>', '', content)
    content = _re.sub(r'<minimax:\w+[^>]*>', '', content)
    content = content.strip()

    # Normalize tool_calls: decode argument strings → dicts
    raw_tc = msg.get("tool_calls") or []
    normalized_tc: list[dict[str, Any]] = []
    for tc in raw_tc:
        fn = tc.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        # Always ensure a non-empty id — required by OpenAI-compat APIs for
        # the matching tool_call_id in follow-up tool result messages.
        call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:16]}"
        normalized_tc.append({
            "id": call_id,
            "type": "function",
            "function": {"name": fn.get("name", ""), "arguments": args},
        })

    normalized_msg: dict[str, Any] = {
        "role": msg.get("role", "assistant"),
        "content": content,
    }
    if normalized_tc:
        normalized_msg["tool_calls"] = normalized_tc

    return {"model": model, "message": normalized_msg, "done": True}


class OpenAICompatAdapter:
    """
    Async adapter for any OpenAI-compatible chat-completions API.

    Sends POST /v1/chat/completions and returns an OllamaResponse so
    all existing orchestrator/parser code works unchanged.

    Supports: OpenAI, Azure OpenAI, Groq, Mistral, Ollama /v1, etc.
    Bearer-token auth; set api_key="" to skip the header.
    """

    def __init__(self, settings: AppSettings) -> None:
        cfg = settings.openai_compat
        self._base_url = _normalize_base_url(cfg.base_url)
        self._api_key = cfg.api_key
        self._model = cfg.model
        self._temperature = cfg.temperature
        self._timeout = float(settings.timeouts.llm_seconds)

    # ── Public interface mirrors OllamaAdapter ────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        stream: bool = False,
    ) -> OllamaResponse:
        """
        Call /v1/chat/completions and return an OllamaResponse.

        Args:
            messages: OpenAI-style message list (same format Ollama uses).
            tools:    Optional list of tool schemas in Ollama/OpenAI function format.
            stream:   Streaming not yet supported.

        Returns:
            OllamaResponse wrapping a normalised response dict.

        Raises:
            LLMConnectionError: Cannot reach the API endpoint.
            LLMTimeoutError:    Request exceeded llm_seconds.
        """
        if stream:
            raise NotImplementedError("Streaming is not yet implemented.")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        log.debug(
            "OpenAI-compat request: model=%s url=%s, %d messages, %d tools",
            self._model, self._base_url, len(messages), len(tools or []),
        )

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        # Use an absolute URL to avoid httpx base_url path-joining ambiguity
        chat_url = f"{self._base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    chat_url,
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                raw: dict[str, Any] = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"OpenAI-compat request timed out after {self._timeout}s. "
                "Increase timeouts.llm_seconds in app_settings.yaml."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Cannot connect to API at {chat_url}. "
                "Check openai_compat.base_url in Settings."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMConnectionError(
                f"API returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:300]}"
            ) from exc

        data = _normalize_to_ollama_response(raw)
        log.debug(
            "OpenAI-compat response: model=%s, tool_calls=%d",
            data.get("model"),
            len(data.get("message", {}).get("tool_calls") or []),
        )
        return OllamaResponse(data)

    async def check_connection(self) -> bool:
        """Return True if the API endpoint is reachable."""
        try:
            headers: dict[str, str] = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=5.0
            ) as client:
                resp = await client.get("/v1/models", headers=headers)
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """
        Try a minimal 1-token chat completion to verify the endpoint, API key,
        and model are all reachable and valid.

        Returns:
            (True, success_message) on success.
            (False, error_message) on any failure.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0.0,
        }
        url = f"{self._base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return True, f"Connected ✓  ({self._base_url})  model={self._model}"
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.TimeoutException:
            return False, f"Timed out connecting to {self._base_url}"
        except httpx.ConnectError as exc:
            return False, f"Cannot connect: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Error: {exc}"
