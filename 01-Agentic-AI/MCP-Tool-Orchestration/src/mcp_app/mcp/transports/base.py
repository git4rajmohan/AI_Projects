"""Abstract transport interface for MCP server communication."""
from __future__ import annotations

import abc
from typing import Any


class BaseTransport(abc.ABC):
    """
    Abstract base for all MCP server transports.

    Subclasses implement start/stop and low-level send/receive
    operations suitable for MCP JSON-RPC style messaging.
    """

    @abc.abstractmethod
    async def start(self) -> None:
        """Start the transport (spawn process, open connection, etc.)."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Cleanly stop the transport, releasing all resources."""

    @abc.abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON-serialisable message to the server."""

    @abc.abstractmethod
    async def receive(self, timeout: float = 30.0) -> dict[str, Any]:
        """
        Receive the next message from the server.

        Args:
            timeout: Seconds to wait before raising ProcessTimeoutError.

        Returns:
            Parsed JSON message dict.
        """

    @property
    @abc.abstractmethod
    def is_alive(self) -> bool:
        """Return True if the underlying connection / process is still running."""
