"""Tests for ToolRegistry namespacing and collisions."""
from __future__ import annotations

import pytest

from mcp_app.core.errors import ToolNotRegisteredError
from mcp_app.core.tool_registry import ToolRegistry


def _make_schema(name: str) -> dict:
    return {"name": name, "description": f"Tool {name}", "inputSchema": {}}


class TestToolRegistry:
    def test_register_and_resolve(self):
        reg = ToolRegistry()
        reg.register("server1", "echo", _make_schema("echo"))
        server_id, tool_name, schema = reg.resolve("server1.echo")
        assert server_id == "server1"
        assert tool_name == "echo"
        assert schema["name"] == "echo"

    def test_namespace_prevents_collision(self):
        reg = ToolRegistry()
        reg.register("server1", "echo", _make_schema("echo"))
        reg.register("server2", "echo", _make_schema("echo"))
        assert len(reg) == 2
        s1, _, _ = reg.resolve("server1.echo")
        s2, _, _ = reg.resolve("server2.echo")
        assert s1 == "server1"
        assert s2 == "server2"

    def test_duplicate_full_name_overwrite(self, caplog):
        """Re-registering same full name overwrites (logged at debug)."""
        reg = ToolRegistry()
        reg.register("srv", "tool", _make_schema("tool"))
        reg.register("srv", "tool", {"name": "tool", "description": "v2"})
        _, _, schema = reg.resolve("srv.tool")
        assert schema["description"] == "v2"

    def test_resolve_unknown_raises(self):
        reg = ToolRegistry()
        with pytest.raises(ToolNotRegisteredError, match="not registered"):
            reg.resolve("ghost.tool")

    def test_get_all_tools_returns_schemas(self):
        reg = ToolRegistry()
        reg.register("s", "t1", _make_schema("t1"))
        reg.register("s", "t2", _make_schema("t2"))
        tools = reg.get_all_tools()
        names = {t["name"] for t in tools}
        assert names == {"t1", "t2"}

    def test_contains(self):
        reg = ToolRegistry()
        reg.register("s", "x", _make_schema("x"))
        assert "s.x" in reg
        assert "s.y" not in reg

    def test_list_names(self):
        reg = ToolRegistry()
        reg.register("a", "t1", _make_schema("t1"))
        reg.register("b", "t2", _make_schema("t2"))
        names = set(reg.list_names())
        assert names == {"a.t1", "b.t2"}

    def test_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register("s", "t", _make_schema("t"))
        assert len(reg) == 1

    @pytest.mark.asyncio
    async def test_build_from_manager(self):
        """build() uses manager.get_managed_servers() and list_tools()."""
        from unittest.mock import AsyncMock, MagicMock
        from mcp_app.mcp.server_manager import ManagedServer, ServerManager, ServerStatus
        from mcp_app.config.schema import ServerConfig

        ms = MagicMock(spec=ManagedServer)
        ms.status = ServerStatus.READY
        ms.tools = [_make_schema("ping")]

        mgr = MagicMock(spec=ServerManager)
        mgr.get_managed_servers.return_value = {"srv": ms}
        mgr.list_tools = AsyncMock(return_value=[_make_schema("ping")])

        reg = ToolRegistry()
        await reg.build(mgr)
        assert "srv.ping" in reg
