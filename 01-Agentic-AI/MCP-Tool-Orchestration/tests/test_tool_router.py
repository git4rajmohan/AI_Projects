"""
Tests for ToolRouter enforcement + truncation using the mock MCP server.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_app.config.schema import (
    AppSettings,
    MCPServersConfig,
    PoliciesConfig,
    ServerConfig,
    ServerPolicy,
    StdioConfig,
)
from mcp_app.core.errors import (
    PolicyDeniedError,
    ServerNotReadyError,
    ToolNotRegisteredError,
)
from mcp_app.core.tool_registry import ToolRegistry
from mcp_app.core.tool_router import ToolRouter
from mcp_app.mcp.server_manager import ManagedServer, ServerManager, ServerStatus

MOCK_SERVER = Path(__file__).parent / "mocks" / "mock_mcp_server" / "server.py"
PYTHON = sys.executable


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings(max_chars: int = 20000) -> AppSettings:
    return AppSettings.model_validate({"limits": {"max_tool_output_chars": max_chars}})


def _policies(**kw) -> PoliciesConfig:
    return PoliciesConfig.model_validate(kw)


def _mock_manager(
    server_id: str,
    status: ServerStatus = ServerStatus.READY,
    call_result: str = "tool output",
    srv_policy: ServerPolicy | None = None,
) -> MagicMock:
    policy = srv_policy or ServerPolicy()
    cfg = ServerConfig(
        id=server_id,
        name="mock",
        enabled=True,
        transport="stdio",
        stdio=StdioConfig(command=PYTHON),
        policy=policy,
    )
    ms = MagicMock(spec=ManagedServer)
    ms.status = status
    ms.config = cfg

    mgr = MagicMock(spec=ServerManager)
    mgr.get_managed_servers.return_value = {server_id: ms}
    mgr.call_tool = AsyncMock(return_value=call_result)
    return mgr


def _registry(*pairs: tuple[str, str]) -> ToolRegistry:
    reg = ToolRegistry()
    for sid, tname in pairs:
        reg.register(sid, tname, {"name": tname, "description": ""})
    return reg


# ── Basic execution ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_executes_tool():
    reg = _registry(("srv", "echo"))
    mgr = _mock_manager("srv", call_result="Echo: hello")
    router = ToolRouter(reg, mgr, _settings(), _policies())
    result = await router.execute("srv.echo", {"text": "hello"})
    assert result == "Echo: hello"
    mgr.call_tool.assert_awaited_once_with("srv", "echo", {"text": "hello"})


@pytest.mark.asyncio
async def test_tool_not_registered_raises():
    reg = _registry()
    mgr = _mock_manager("srv")
    router = ToolRouter(reg, mgr, _settings(), _policies())
    with pytest.raises(ToolNotRegisteredError):
        await router.execute("srv.nonexistent", {})


@pytest.mark.asyncio
async def test_server_not_ready_raises():
    reg = _registry(("srv", "tool"))
    mgr = _mock_manager("srv", status=ServerStatus.FAILED)
    router = ToolRouter(reg, mgr, _settings(), _policies())
    with pytest.raises(ServerNotReadyError):
        await router.execute("srv.tool", {})


# ── Policy enforcement ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_global_deny_blocks():
    reg = _registry(("srv", "rm"))
    mgr = _mock_manager("srv")
    pol = _policies(global_denied_tools=["rm"])
    router = ToolRouter(reg, mgr, _settings(), pol)
    with pytest.raises(PolicyDeniedError):
        await router.execute("srv.rm", {})


@pytest.mark.asyncio
async def test_per_server_deny_blocks():
    srv_pol = ServerPolicy(denied_tools=["secret"])
    reg = _registry(("srv", "secret"))
    mgr = _mock_manager("srv", srv_policy=srv_pol)
    router = ToolRouter(reg, mgr, _settings(), _policies())
    with pytest.raises(PolicyDeniedError):
        await router.execute("srv.secret", {})


@pytest.mark.asyncio
async def test_global_allow_whitelist_blocks_unlisted():
    reg = _registry(("srv", "unlisted"))
    mgr = _mock_manager("srv")
    pol = _policies(global_allowed_tools=["only_this"])
    router = ToolRouter(reg, mgr, _settings(), pol)
    with pytest.raises(PolicyDeniedError):
        await router.execute("srv.unlisted", {})


# ── Output truncation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_truncation_applied():
    reg = _registry(("srv", "big"))
    big = "A" * 5000
    mgr = _mock_manager("srv", call_result=big)
    settings = _settings(max_chars=100)
    router = ToolRouter(reg, mgr, settings, _policies())
    result = await router.execute("srv.big", {})
    assert len(result) <= 150  # truncated + suffix
    assert "truncated" in result


@pytest.mark.asyncio
async def test_no_truncation_when_within_limit():
    reg = _registry(("srv", "small"))
    mgr = _mock_manager("srv", call_result="hi")
    router = ToolRouter(reg, mgr, _settings(max_chars=1000), _policies())
    result = await router.execute("srv.small", {})
    assert result == "hi"


# ── Integration with real mock server ────────────────────────────────────────

@pytest.mark.asyncio
async def test_real_mock_server_echo():
    """Spawn actual mock server process and call the echo tool."""
    from mcp_app.mcp.transports.stdio import StdioTransport
    from mcp_app.mcp.client import MCPClient

    transport = StdioTransport(
        command=PYTHON,
        args=[str(MOCK_SERVER)],
    )
    await transport.start()
    try:
        client = MCPClient(transport, "mock", call_timeout=10.0)
        tools = await client.list_tools()
        assert any(t["name"] == "echo" for t in tools)

        result = await client.call_tool("echo", {"text": "hello"})
        assert "hello" in str(result)
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_real_mock_server_add():
    from mcp_app.mcp.transports.stdio import StdioTransport
    from mcp_app.mcp.client import MCPClient

    transport = StdioTransport(command=PYTHON, args=[str(MOCK_SERVER)])
    await transport.start()
    try:
        client = MCPClient(transport, "mock")
        result = await client.call_tool("add", {"a": 3, "b": 4})
        assert "7" in str(result)
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_real_mock_server_unknown_tool_raises():
    from mcp_app.mcp.transports.stdio import StdioTransport
    from mcp_app.mcp.client import MCPClient
    from mcp_app.core.errors import MCPToolNotFoundError

    transport = StdioTransport(command=PYTHON, args=[str(MOCK_SERVER)])
    await transport.start()
    try:
        client = MCPClient(transport, "mock")
        with pytest.raises(MCPToolNotFoundError):
            await client.call_tool("nonexistent", {})
    finally:
        await transport.stop()
