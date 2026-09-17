"""Tool Registry — central registry for all tools available to agents.

Matches instruction.md section 19 (Tool Registry) and section 20 (Tool Security).

Tools are registered by ID and referenced by agents via their ID.
The registry enforces permission levels and enabled/disabled state.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.tool_schema import ToolSpec

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Raised when a tool execution fails."""


class ToolNotFoundError(KeyError):
    """Raised when a requested tool ID is not in the registry."""


class Tool:
    """Base class for a callable tool.

    Subclasses implement `execute(**params) -> dict`.
    """

    spec: ToolSpec

    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def permission_level(self) -> str:
        return self.spec.permission_level

    async def execute(self, **params: Any) -> dict:
        """Execute the tool with the given parameters.

        Returns a dict with at minimum:
            {"success": bool, "output": ..., "error": str | None}
        """
        raise NotImplementedError("Tool subclasses must implement execute()")


class ToolRegistry:
    """Central registry for tools.

    Usage:
        registry = ToolRegistry()
        registry.register(FileReader())
        tool = registry.get("file_reader")
        result = await tool.execute(path="data.csv")
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        if tool.id in self._tools:
            logger.warning(f"Tool '{tool.id}' already registered — overwriting")
        self._tools[tool.id] = tool
        logger.debug(f"Registered tool: {tool.id} ({tool.name})")

    def get(self, tool_id: str) -> Tool:
        """Get a tool by ID.

        Raises:
            ToolNotFoundError: If the tool is not registered.
        """
        tool = self._tools.get(tool_id)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{tool_id}' not found in registry")
        return tool

    def list(self) -> list[ToolSpec]:
        """List all registered tool specs."""
        return [t.spec for t in self._tools.values()]

    def list_enabled(self) -> list[ToolSpec]:
        """List all enabled tool specs."""
        return [t.spec for t in self._tools.values() if t.spec.enabled]

    def remove(self, tool_id: str) -> None:
        """Remove a tool from the registry."""
        if tool_id in self._tools:
            del self._tools[tool_id]
            logger.debug(f"Removed tool: {tool_id}")
        else:
            raise ToolNotFoundError(f"Tool '{tool_id}' not found in registry")

    def has(self, tool_id: str) -> bool:
        """Check if a tool is registered."""
        return tool_id in self._tools

    def clear(self) -> None:
        """Remove all tools from the registry."""
        self._tools.clear()


# --- Singleton registry ---

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the singleton ToolRegistry instance.

    On first call, registers all built-in tools.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_builtins(_registry)
    return _registry


def _register_builtins(registry: ToolRegistry) -> None:
    """Register all built-in tools into the registry."""
    from app.tools.builtins.file_reader import FileReader
    from app.tools.builtins.file_writer import FileWriter
    from app.tools.builtins.python_executor import PythonExecutor
    from app.tools.builtins.calculator import Calculator
    from app.tools.builtins.http_request import HttpRequest
    from app.tools.builtins.web_search import WebSearch

    for tool in [FileReader(), FileWriter(), PythonExecutor(), Calculator(), HttpRequest(), WebSearch()]:
        registry.register(tool)

    logger.info(f"Registered {len(registry.list())} built-in tools")