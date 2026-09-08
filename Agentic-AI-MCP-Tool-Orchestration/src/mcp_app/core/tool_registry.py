"""Tool registry: merges tools across servers with namespacing."""
from __future__ import annotations

from typing import Any

from mcp_app.core.errors import ToolNotRegisteredError
from mcp_app.mcp.server_manager import ServerManager
from mcp_app.observability.logger import get_logger

log = get_logger(__name__)

# A registered tool entry
ToolEntry = dict[str, Any]  # {server_id, tool_name, schema}


class ToolRegistry:
    """
    Central registry of all tools exposed by managed MCP servers.

    Tools are namespaced as ``<server_id>.<tool_name>`` to avoid collision.
    Collision policy: first registration wins; duplicates are logged.
    """

    def __init__(self) -> None:
        # full_name -> entry
        self._registry: dict[str, ToolEntry] = {}

    # ── Build ─────────────────────────────────────────────────────────────────

    async def build(self, manager: ServerManager) -> None:
        """Populate the registry from all READY servers."""
        self._registry.clear()
        for server_id, ms in manager.get_managed_servers().items():
            from mcp_app.mcp.server_manager import ServerStatus  # local import
            if ms.status != ServerStatus.READY:
                continue
            tools = await manager.list_tools(server_id)
            for tool_def in tools:
                tool_name: str = tool_def.get("name", "")
                if not tool_name:
                    continue
                full_name = f"{server_id}.{tool_name}"
                if full_name in self._registry:
                    log.warning(
                        "Tool '%s' already registered; skipping duplicate.", full_name
                    )
                    continue
                self._registry[full_name] = {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "full_name": full_name,
                    "schema": tool_def,
                }
        log.info("ToolRegistry built: %d tools.", len(self._registry))

    def register(
        self, server_id: str, tool_name: str, schema: dict[str, Any]
    ) -> None:
        """Manually register a single tool (used in tests)."""
        full_name = f"{server_id}.{tool_name}"
        if full_name in self._registry:
            log.debug("Tool '%s' already in registry; overwriting.", full_name)
        self._registry[full_name] = {
            "server_id": server_id,
            "tool_name": tool_name,
            "full_name": full_name,
            "schema": schema,
        }

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_all_tools(self) -> list[dict[str, Any]]:
        """
        Return tool schemas formatted for inclusion in an LLM request.

        Returns each tool's ``schema`` dict (MCP tool definition format).
        """
        return [entry["schema"] for entry in self._registry.values()]

    def resolve(self, full_name: str) -> tuple[str, str, dict[str, Any]]:
        """
        Resolve a namespaced tool name.

        Args:
            full_name: ``<server_id>.<tool_name>``

        Returns:
            Tuple of (server_id, tool_name, schema).

        Raises:
            ToolNotRegisteredError: if not found.
        """
        entry = self._registry.get(full_name)
        if entry is None:
            raise ToolNotRegisteredError(full_name)
        return entry["server_id"], entry["tool_name"], entry["schema"]

    def __len__(self) -> int:
        return len(self._registry)

    def __contains__(self, full_name: str) -> bool:
        return full_name in self._registry

    def list_names(self) -> list[str]:
        return list(self._registry.keys())
