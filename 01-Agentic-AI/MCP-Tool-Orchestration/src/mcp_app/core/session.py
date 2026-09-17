"""Session state: messages, tool calls, serialisation."""
from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: str = field(
        default_factory=lambda: datetime.datetime.now(
            tz=datetime.timezone.utc
        ).isoformat()
    )


@dataclass
class ToolCallRecord:
    tool: str
    args: dict[str, Any]
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: str = field(
        default_factory=lambda: datetime.datetime.now(
            tz=datetime.timezone.utc
        ).isoformat()
    )
    finished_at: Optional[str] = None

    def finish(self, result: Optional[str] = None, error: Optional[str] = None) -> None:
        self.result = result
        self.error = error
        self.finished_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


class Session:
    """
    Holds all state for a single conversation turn (or multi-turn session).
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        model: str = "",
    ) -> None:
        self.session_id: str = session_id or str(uuid.uuid4())
        self.model: str = model
        self.messages: list[Message] = []
        self.tool_calls: list[ToolCallRecord] = []
        self.created_at: str = datetime.datetime.now(
            tz=datetime.timezone.utc
        ).isoformat()

    # ── Message helpers ───────────────────────────────────────────────────────

    def add_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        msg = Message(role=role, content=content, metadata=metadata or {})
        self.messages.append(msg)
        return msg

    def add_tool_call(self, tool: str, args: dict[str, Any]) -> ToolCallRecord:
        rec = ToolCallRecord(tool=tool, args=args)
        self.tool_calls.append(rec)
        return rec

    def to_ollama_messages(self) -> list[dict[str, Any]]:
        """Return messages in Ollama / OpenAI API format (role/content dicts).

        Includes tool_calls on assistant messages and tool_call_id on tool
        messages when present in metadata — required for OpenAI-compatible
        multi-turn tool calling.  Ollama ignores the extra fields.
        """
        msgs = []
        for m in self.messages:
            d: dict[str, Any] = {"role": m.role, "content": m.content}
            images = m.metadata.get("images")
            if images:
                d["images"] = images
            # Emit raw tool_calls for assistant messages (OpenAI multi-turn requirement)
            raw_tc = m.metadata.get("tool_calls")
            if m.role == "assistant" and raw_tc:
                d["tool_calls"] = raw_tc
            # Emit tool_call_id for tool result messages (required by OpenAI-compat APIs).
            # Always include the field — an absent tool_call_id causes HTTP 400.
            if m.role == "tool":
                tool_call_id = m.metadata.get("tool_call_id", "")
                d["tool_call_id"] = tool_call_id
            msgs.append(d)
        return msgs

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "model": self.model,
            "created_at": self.created_at,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "ts": m.ts,
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
            "tool_calls": [
                {
                    "tool": tc.tool,
                    "args": tc.args,
                    "result": tc.result,
                    "error": tc.error,
                    "started_at": tc.started_at,
                    "finished_at": tc.finished_at,
                }
                for tc in self.tool_calls
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False, indent=2)
