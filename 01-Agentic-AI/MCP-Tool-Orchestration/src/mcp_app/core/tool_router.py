"""Tool router: policy enforcement + execution with output truncation."""
from __future__ import annotations

import re
from typing import Any

from mcp_app.config.schema import AppSettings, PoliciesConfig
from mcp_app.core.errors import (
    PolicyDeniedError,
    ProcessTimeoutError,
    ServerNotReadyError,
    ToolNotRegisteredError,
    TransportError,
)
from mcp_app.core.tool_registry import ToolRegistry
from mcp_app.mcp.server_manager import ServerManager, ServerStatus
from mcp_app.observability.logger import get_logger
from mcp_app.observability.tracing import trace_event
from mcp_app.utils.retry import retry_async

log = get_logger(__name__)


class ToolRouter:
    """
    Orchestrates tool execution with:
      - Policy allow/deny checks (global and per-server)
      - Server health checks
      - Output truncation (configurable limit)
      - Full-output tracing before truncation
    """

    def __init__(
        self,
        registry: ToolRegistry,
        manager: ServerManager,
        settings: AppSettings,
        policies: PoliciesConfig,
    ) -> None:
        self._registry = registry
        self._manager = manager
        self._settings = settings
        self._policies = policies
        self._max_chars = settings.limits.max_tool_output_chars

    async def execute(
        self,
        full_tool_name: str,
        args: dict[str, Any],
        session_id: str = "",
    ) -> str:
        """
        Execute a tool call, enforcing policies and truncating output.

        Args:
            full_tool_name: Namespaced ``<server_id>.<tool_name>``.
            args:           Tool arguments dict.
            session_id:     For tracing correlation.

        Returns:
            Tool output as a string, truncated to limits.max_tool_output_chars.

        Raises:
            ToolNotRegisteredError: tool is unknown.
            PolicyDeniedError:      blocked by policy.
            ServerNotReadyError:    server is not READY.
        """
        # 1. Resolve tool
        try:
            server_id, tool_name, schema = self._registry.resolve(full_tool_name)
        except ToolNotRegisteredError:
            raise

        # 2. Server health check
        managed = self._manager.get_managed_servers().get(server_id)
        if managed is None or managed.status != ServerStatus.READY:
            status_str = managed.status.value if managed else "unknown"
            raise ServerNotReadyError(server_id, status_str)

        # 3. Global deny list
        self._check_global_policy(full_tool_name, tool_name)

        # 4. Per-server policy
        self._check_server_policy(server_id, tool_name, managed.config)

        # 5. Execute
        trace_event(
            "tool_call_start",
            {"tool": full_tool_name, "args": args},
            session_id=session_id,
        )
        # ponytail: retry only transient transport faults (timeout/connection);
        # policy/validation errors raise before this line and must never be retried
        raw_output = await retry_async(
            self._manager.call_tool, server_id, tool_name, args,
            retries=2, exceptions=(ProcessTimeoutError, TransportError),
        )

        # Normalise output to string
        if not isinstance(raw_output, str):
            import json
            raw_output = json.dumps(raw_output, default=str)

        # 6. Trace full output (before truncation)
        trace_event(
            "tool_call_result",
            {"tool": full_tool_name, "output_length": len(raw_output), "output": raw_output},
            session_id=session_id,
        )

        # 7. Strip embedded binary (base64 images) then truncate for LLM consumption
        clean_output = self._strip_binary_data(raw_output)
        truncated = self._truncate(clean_output)
        if len(clean_output) > self._max_chars:
            log.debug(
                "Tool '%s' output truncated: %d → %d chars",
                full_tool_name, len(clean_output), len(truncated),
            )

        return truncated

    # ── Policy helpers ────────────────────────────────────────────────────────

    def _check_global_policy(
        self, full_tool_name: str, bare_tool_name: str
    ) -> None:
        denied = self._policies.global_denied_tools
        if denied:
            for pattern in denied:
                if pattern in (full_tool_name, bare_tool_name):
                    raise PolicyDeniedError(
                        full_tool_name, "globally denied by policies.yaml"
                    )

        allowed = self._policies.global_allowed_tools
        if allowed:
            # Non-empty allowed list acts as whitelist
            for pattern in allowed:
                if pattern in (full_tool_name, bare_tool_name):
                    return
            raise PolicyDeniedError(
                full_tool_name,
                "not in global_allowed_tools whitelist",
            )

    def _check_server_policy(
        self, server_id: str, tool_name: str, config: Any
    ) -> None:
        server_policy = config.policy
        denied = server_policy.denied_tools
        if tool_name in denied:
            raise PolicyDeniedError(
                f"{server_id}.{tool_name}",
                f"denied by server '{server_id}' policy",
            )
        allowed = server_policy.allowed_tools
        if allowed and tool_name not in allowed:
            raise PolicyDeniedError(
                f"{server_id}.{tool_name}",
                f"not in server '{server_id}' allowed_tools whitelist",
            )

    def _strip_binary_data(self, output: str) -> str:
        """Replace embedded base64 image data with a short placeholder.

        Playwright's browser_take_screenshot embeds a full base64-encoded PNG
        in the JSON response.  A non-vision LLM cannot use the image and the
        data can exceed 200 KB, overwhelming the context window.  When
        --output-dir is set on the Playwright server the file is also saved to
        disk, so the base64 payload is redundant.
        """
        placeholder = '"[IMAGE DATA REMOVED - screenshot saved to output-dir]"'

        # Match JSON "data": "<long base64>" key-value pairs
        key_pattern = re.compile(r'"data"\s*:\s*"[A-Za-z0-9+/\r\n]{200,}={0,2}"')
        cleaned, n1 = key_pattern.subn(f'"data": {placeholder}', output)

        # Match any quoted string that is purely base64 and longer than 500 chars
        val_pattern = re.compile(r'"[A-Za-z0-9+/\r\n]{500,}={0,2}"')
        cleaned, n2 = val_pattern.subn(placeholder, cleaned)

        total = n1 + n2
        if total:
            log.debug("Stripped %d base64 image blob(s) from tool output", total)
        return cleaned

    def _truncate(self, output: str) -> str:
        if len(output) <= self._max_chars:
            return output
        suffix = f"\n...[truncated to {self._max_chars} chars]"
        return output[: self._max_chars - len(suffix)] + suffix
