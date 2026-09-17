"""HTTP transport – stub placeholder (not implemented)."""
from __future__ import annotations

from typing import Any

from mcp_app.mcp.transports.base import BaseTransport


class HttpTransport(BaseTransport):
    """
    Placeholder HTTP/SSE transport for MCP servers.

    Not implemented. Raises NotImplementedError on all calls.
    """

    async def start(self) -> None:
        raise NotImplementedError("HTTP transport is not yet implemented.")

    async def stop(self) -> None:
        pass

    async def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError("HTTP transport is not yet implemented.")

    async def receive(self, timeout: float = 30.0) -> dict[str, Any]:
        raise NotImplementedError("HTTP transport is not yet implemented.")

    @property
    def is_alive(self) -> bool:
        return False
