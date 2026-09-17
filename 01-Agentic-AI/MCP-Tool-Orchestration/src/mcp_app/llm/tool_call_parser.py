"""Parse tool-call requests from Ollama LLM responses."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from mcp_app.core.errors import ToolCallParseError


@dataclass
class ParsedToolCall:
    """A single tool call extracted from an LLM response."""
    full_name: str          # as returned by LLM (may need namespace lookup)
    args: dict[str, Any]
    call_id: str = ""       # Ollama tool_call id if present


def parse_tool_calls(response: dict[str, Any]) -> list[ParsedToolCall]:
    """
    Extract tool calls from an Ollama chat response dict.

    Ollama response structure (when tools are called):
    {
      "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
          {
            "id": "...",
            "type": "function",
            "function": {
              "name": "tool_name",
              "arguments": {...}
            }
          }
        ]
      }
    }

    Returns an empty list if no tool calls are present.

    Raises:
        ToolCallParseError: if tool_calls list is malformed.
    """
    message = response.get("message", {})
    raw_calls = message.get("tool_calls")
    if not raw_calls:
        return []

    if not isinstance(raw_calls, list):
        raise ToolCallParseError(
            f"Expected tool_calls to be a list, got {type(raw_calls).__name__}"
        )

    parsed: list[ParsedToolCall] = []
    for i, call in enumerate(raw_calls):
        if not isinstance(call, dict):
            raise ToolCallParseError(f"tool_calls[{i}] is not a dict: {call!r}")

        call_id = call.get("id", "")
        fn = call.get("function", {})
        if not isinstance(fn, dict):
            raise ToolCallParseError(
                f"tool_calls[{i}].function is not a dict: {fn!r}"
            )

        name = fn.get("name", "")
        if not name:
            raise ToolCallParseError(
                f"tool_calls[{i}].function.name is empty or missing."
            )

        arguments = fn.get("arguments", {})
        # Ollama may return arguments as a JSON string
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ToolCallParseError(
                    f"tool_calls[{i}].function.arguments is not valid JSON: "
                    f"{arguments!r}"
                ) from exc

        if not isinstance(arguments, dict):
            raise ToolCallParseError(
                f"tool_calls[{i}].function.arguments must be a JSON object, "
                f"got {type(arguments).__name__}: {arguments!r}"
            )

        parsed.append(ParsedToolCall(full_name=name, args=arguments, call_id=call_id))

    return parsed


def has_tool_calls(response: dict[str, Any]) -> bool:
    """Quick check: does the response contain any tool calls?"""
    message = response.get("message", {})
    calls = message.get("tool_calls")
    return bool(calls)


def get_assistant_text(response: dict[str, Any]) -> str:
    """Extract the plain text content from an Ollama assistant response."""
    return response.get("message", {}).get("content", "")


def parse_tool_calls_from_text(content: str) -> list[ParsedToolCall]:
    """
    Fallback parser: extract tool calls from LLM text when the model outputs
    JSON tool calls as text rather than using the structured tool_calls format.

    Supports these formats inside ```json blocks or as bare JSON objects:
      {"tool": "name", "args": {...}}
      {"function": "name", "arguments": {...}}
      {"name": "name", "arguments": {...}}
      {"tool_name": "name", "args": {...}}
    """
    if not content:
        return []

    raw_candidates: list[str] = []

    # 1. JSON code blocks  (```json ... ``` or ``` ... ```)
    for m in re.finditer(r'```(?:json)?\s*([\s\S]*?)```', content):
        raw_candidates.append(m.group(1).strip())

    # 2. Use raw_decode to extract ALL top-level JSON objects from the text.
    #    This correctly handles nested braces unlike a simple [^{}] regex.
    #    raw_decode returns (obj, end_idx) where end_idx is absolute in the string.
    decoder = json.JSONDecoder()
    i = 0
    while i < len(content):
        idx = content.find('{', i)
        if idx == -1:
            break
        try:
            obj, end_idx = decoder.raw_decode(content, idx)
            raw_candidates.append(content[idx:end_idx])  # end_idx is absolute
            i = end_idx
        except json.JSONDecodeError:
            i = idx + 1

    seen: set[str] = set()
    results: list[ParsedToolCall] = []

    for candidate in raw_candidates:
        candidate = candidate.strip()
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        # Must contain a tool-name-like key to avoid false positives
        if not any(k in obj for k in ('tool', 'tool_name', 'function', 'name')):
            continue

        # Format: {"tool": "name", "args": {...}}
        if isinstance(obj.get('tool'), str) and isinstance(obj.get('args'), dict):
            results.append(ParsedToolCall(full_name=obj['tool'], args=obj['args']))
            continue

        # Format: {"tool_name": "name", "args": {...}}
        if isinstance(obj.get('tool_name'), str) and isinstance(obj.get('args'), dict):
            results.append(ParsedToolCall(full_name=obj['tool_name'], args=obj['args']))
            continue

        # Format: {"function": "name", "arguments": {...}}
        if isinstance(obj.get('function'), str):
            args = obj.get('arguments') or obj.get('args') or {}
            if isinstance(args, dict):
                results.append(ParsedToolCall(full_name=obj['function'], args=args))
                continue

        # Format: {"name": "name", "arguments": {...}}
        if isinstance(obj.get('name'), str) and isinstance(obj.get('arguments'), dict):
            results.append(ParsedToolCall(full_name=obj['name'], args=obj['arguments']))
            continue

    return results
