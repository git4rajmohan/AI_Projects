"""Application-wide exception hierarchy."""
from __future__ import annotations


class MCPAppError(Exception):
    """Base class for all mcp_app errors."""


# ── Config errors ────────────────────────────────────────────────────────────

class ConfigError(MCPAppError):
    """Raised when configuration is invalid or missing."""


class DuplicateServerIDError(ConfigError):
    """Two servers share the same id."""

    def __init__(self, server_id: str) -> None:
        super().__init__(
            f"Duplicate server id '{server_id}' found in mcp_servers.yaml. "
            "Each server must have a unique id."
        )


class UnknownTransportError(ConfigError):
    """Server specifies an unsupported transport."""

    def __init__(self, server_id: str, transport: str) -> None:
        super().__init__(
            f"Server '{server_id}' uses unknown transport '{transport}'. "
            "Supported transports: stdio."
        )


class MissingStdioCommandError(ConfigError):
    """stdio server has no command specified."""

    def __init__(self, server_id: str) -> None:
        super().__init__(
            f"Server '{server_id}' transport=stdio is missing required field "
            "'stdio.command'."
        )


# ── Transport/process errors ─────────────────────────────────────────────────

class TransportError(MCPAppError):
    """Low-level transport failure."""


class ProcessStartError(TransportError):
    """Could not start the server process."""


class ProcessTimeoutError(TransportError):
    """A read/write operation timed out."""


class ProcessExitedError(TransportError):
    """The server process exited unexpectedly."""


# ── MCP protocol errors ──────────────────────────────────────────────────────

class MCPProtocolError(MCPAppError):
    """MCP JSON-RPC response was malformed."""


class MCPToolNotFoundError(MCPAppError):
    """Tool name does not exist on the server."""

    def __init__(self, server_id: str, tool_name: str) -> None:
        super().__init__(f"Tool '{tool_name}' not found on server '{server_id}'.")


# ── Policy / routing errors ──────────────────────────────────────────────────

class PolicyDeniedError(MCPAppError):
    """Tool call blocked by policy."""

    def __init__(self, tool: str, reason: str) -> None:
        super().__init__(f"Tool '{tool}' denied by policy: {reason}")


class ToolNotRegisteredError(MCPAppError):
    """Tool name is not in the registry."""

    def __init__(self, full_name: str) -> None:
        super().__init__(
            f"Tool '{full_name}' is not registered. "
            "Run 'mcp list-tools' to see available tools."
        )


class ServerNotReadyError(MCPAppError):
    """Server is not in READY state."""

    def __init__(self, server_id: str, status: str) -> None:
        super().__init__(
            f"Server '{server_id}' is not ready (status={status}). "
            "Cannot execute tool calls."
        )


# ── LLM errors ───────────────────────────────────────────────────────────────

class LLMError(MCPAppError):
    """Base class for LLM adapter failures."""


class LLMTimeoutError(LLMError):
    """LLM call exceeded configured timeout."""


class LLMConnectionError(LLMError):
    """Cannot reach the Ollama server."""


class ToolCallParseError(LLMError):
    """Could not parse a tool-call from LLM output."""
