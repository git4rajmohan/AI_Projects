"""High-level MCP JSON-RPC client built on top of a transport."""
from __future__ import annotations

import json
import uuid
from typing import Any

from mcp_app.core.errors import MCPProtocolError, MCPToolNotFoundError
from mcp_app.mcp.transports.base import BaseTransport
from mcp_app.observability.logger import get_logger

log = get_logger(__name__)

# Type alias for a tool definition returned by list_tools
ToolDefinition = dict[str, Any]


class MCPClient:
    """
    MCP protocol client.

    Wraps a BaseTransport and provides:
      - list_tools() -> list[ToolDefinition]
      - call_tool(tool_name, args) -> result string/dict

    Assumes the server speaks newline-delimited JSON-RPC 2.0.
    """

    def __init__(
        self,
        transport: BaseTransport,
        server_id: str,
        call_timeout: float = 30.0,
    ) -> None:
        self._transport = transport
        self._server_id = server_id
        self._call_timeout = call_timeout

    # ── Public API ────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """
        Perform the MCP initialization handshake:
          1. Send ``initialize`` request with protocol version + client info.
          2. Read the server's ``initialize`` result.
          3. Send ``notifications/initialized`` notification (no response expected).

        Must be called once before any other requests.
        """
        req_id = str(uuid.uuid4())
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {"listChanged": False},
                    "sampling": {},
                },
                "clientInfo": {"name": "mcp-app", "version": "0.1.0"},
            },
        }
        log.debug("→ [%s] initialize", self._server_id)
        await self._transport.send(request)
        # Read responses, skipping any notifications (no id field)
        for _ in range(10):
            resp = await self._transport.receive(timeout=self._call_timeout)
            if isinstance(resp, dict) and resp.get("id") == req_id:
                break
        else:
            raise MCPProtocolError(
                f"Server '{self._server_id}' did not respond to initialize"
            )
        # Send the initialized notification (no id — server must not reply)
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        await self._transport.send(notification)
        log.debug("[%s] initialization complete", self._server_id)

    async def list_tools(self) -> list[ToolDefinition]:
        """
        Request the server's tool manifest.

        Returns a list of tool definition dicts:
          { "name": str, "description": str, "inputSchema": {...} }
        """
        resp = await self._rpc("tools/list", {})
        tools = resp.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise MCPProtocolError(
                f"Server '{self._server_id}' returned invalid tools/list response: "
                f"expected list, got {type(tools).__name__}"
            )
        return tools

    async def call_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> Any:
        """
        Invoke a tool on the server.

        Returns:
            The tool result (string, dict, or list depending on server).

        Raises:
            MCPToolNotFoundError: if server says tool does not exist.
            MCPProtocolError: on malformed response.
        """
        resp = await self._rpc(
            "tools/call", {"name": tool_name, "arguments": args}
        )

        if "error" in resp:
            err = resp["error"]
            code = err.get("code", -1)
            msg = err.get("message", "unknown error")
            # MCP convention: -32601 = method/tool not found
            if code == -32601 or "not found" in msg.lower():
                raise MCPToolNotFoundError(self._server_id, tool_name)
            raise MCPProtocolError(
                f"Server '{self._server_id}' error on tool '{tool_name}': "
                f"[{code}] {msg}"
            )

        result = resp.get("result", {})
        # MCP content blocks: [{type: text, text: "..."}]
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    else:
                        parts.append(json.dumps(block))
                return "\n".join(parts)
        return result

    # ── JSON-RPC helpers ─────────────────────────────────────────────────────

    async def _rpc(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        req_id = str(uuid.uuid4())
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        log.debug("→ [%s] %s %s", self._server_id, method, params)
        await self._transport.send(request)
        # Loop to find our response, skipping notifications and out-of-order replies.
        # Some servers (e.g. Playwright) send responses asynchronously so earlier
        # request responses may arrive while we wait for a later one.
        for _ in range(50):
            resp = await self._transport.receive(timeout=self._call_timeout)
            log.debug("← [%s] %s", self._server_id, resp)
            if not isinstance(resp, dict):
                raise MCPProtocolError(
                    f"Server '{self._server_id}' returned non-dict response: {resp!r}"
                )
            resp_id = resp.get("id")
            if resp_id == req_id:
                # This is our response
                return resp
            if resp_id is None:
                # Notification (no id) — skip silently
                log.debug("[%s] skipping notification: %s", self._server_id, resp.get("method"))
                continue
            # Response for a different in-flight request — skip and keep waiting
            log.debug(
                "[%s] skipping out-of-order response id=%r (want %r)",
                self._server_id, resp_id, req_id,
            )
            continue
        raise MCPProtocolError(
            f"Server '{self._server_id}' did not send a response for '{method}'"
        )
