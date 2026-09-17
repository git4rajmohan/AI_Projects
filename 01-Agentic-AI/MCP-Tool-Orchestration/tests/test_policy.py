"""Tests for policy allow/deny evaluation via ToolRouter."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_app.config.schema import (
    AppSettings, PoliciesConfig, ServerConfig, ServerPolicy, StdioConfig,
)
from mcp_app.core.errors import PolicyDeniedError, ServerNotReadyError
from mcp_app.core.tool_registry import ToolRegistry
from mcp_app.core.tool_router import ToolRouter
from mcp_app.mcp.server_manager import ManagedServer, ServerManager, ServerStatus


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _build_settings(**overrides) -> AppSettings:
    return AppSettings.model_validate({
        "limits": {"max_tool_output_chars": 100},
        **overrides,
    })


def _build_policies(**overrides) -> PoliciesConfig:
    return PoliciesConfig.model_validate(overrides)


def _build_registry(*tools: tuple[str, str]) -> ToolRegistry:
    """tools: [(server_id, tool_name), ...]"""
    reg = ToolRegistry()
    for server_id, tool_name in tools:
        reg.register(server_id, tool_name, {"name": tool_name, "description": ""})
    return reg


def _build_manager_mock(
    server_id: str,
    status: ServerStatus = ServerStatus.READY,
    policy: ServerPolicy | None = None,
    call_result: str = "ok",
) -> MagicMock:
    """Return a mock ServerManager that returns *call_result* for any call_tool."""
    srv_policy = policy or ServerPolicy()
    srv_cfg = ServerConfig(
        id=server_id,
        name="test",
        enabled=True,
        transport="stdio",
        stdio=StdioConfig(command="python"),
        policy=srv_policy,
    )
    ms = MagicMock(spec=ManagedServer)
    ms.status = status
    ms.config = srv_cfg

    mgr = MagicMock(spec=ServerManager)
    mgr.get_managed_servers.return_value = {server_id: ms}
    mgr.call_tool = AsyncMock(return_value=call_result)
    return mgr


# ── Global deny ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_global_denied_tool_blocked():
    reg = _build_registry(("srv", "bad_tool"))
    mgr = _build_manager_mock("srv")
    pol = _build_policies(global_denied_tools=["bad_tool"])
    router = ToolRouter(reg, mgr, _build_settings(), pol)

    with pytest.raises(PolicyDeniedError, match="globally denied"):
        await router.execute("srv.bad_tool", {})


@pytest.mark.asyncio
async def test_full_name_global_denied():
    reg = _build_registry(("srv", "tool"))
    mgr = _build_manager_mock("srv")
    pol = _build_policies(global_denied_tools=["srv.tool"])
    router = ToolRouter(reg, mgr, _build_settings(), pol)

    with pytest.raises(PolicyDeniedError):
        await router.execute("srv.tool", {})


# ── Global allow whitelist ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_global_allowed_whitelist_permits():
    reg = _build_registry(("srv", "ok_tool"))
    mgr = _build_manager_mock("srv", call_result="result")
    pol = _build_policies(global_allowed_tools=["ok_tool"])
    router = ToolRouter(reg, mgr, _build_settings(), pol)

    result = await router.execute("srv.ok_tool", {})
    assert result == "result"


@pytest.mark.asyncio
async def test_global_allowed_whitelist_blocks_unlisted():
    reg = _build_registry(("srv", "other_tool"))
    mgr = _build_manager_mock("srv")
    pol = _build_policies(global_allowed_tools=["only_this"])
    router = ToolRouter(reg, mgr, _build_settings(), pol)

    with pytest.raises(PolicyDeniedError, match="whitelist"):
        await router.execute("srv.other_tool", {})


# ── Per-server deny ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_server_denied_tool_blocked():
    server_policy = ServerPolicy(denied_tools=["secret_tool"])
    reg = _build_registry(("srv", "secret_tool"))
    mgr = _build_manager_mock("srv", policy=server_policy)
    pol = _build_policies()
    router = ToolRouter(reg, mgr, _build_settings(), pol)

    with pytest.raises(PolicyDeniedError, match="denied by server"):
        await router.execute("srv.secret_tool", {})


@pytest.mark.asyncio
async def test_server_allowed_whitelist_blocks():
    server_policy = ServerPolicy(allowed_tools=["allowed"])
    reg = _build_registry(("srv", "not_allowed"))
    mgr = _build_manager_mock("srv", policy=server_policy)
    pol = _build_policies()
    router = ToolRouter(reg, mgr, _build_settings(), pol)

    with pytest.raises(PolicyDeniedError, match="whitelist"):
        await router.execute("srv.not_allowed", {})


# ── Server not ready ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_server_not_ready_blocks():
    reg = _build_registry(("srv", "tool"))
    mgr = _build_manager_mock("srv", status=ServerStatus.FAILED)
    pol = _build_policies()
    router = ToolRouter(reg, mgr, _build_settings(), pol)

    with pytest.raises(ServerNotReadyError):
        await router.execute("srv.tool", {})


# ── Output truncation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_output_truncated():
    reg = _build_registry(("srv", "big_tool"))
    long_output = "x" * 200
    mgr = _build_manager_mock("srv", call_result=long_output)
    settings = _build_settings(**{"limits": {"max_tool_output_chars": 50}})
    pol = _build_policies()
    router = ToolRouter(reg, mgr, settings, pol)

    result = await router.execute("srv.big_tool", {})
    assert len(result) <= 50 + len("\n...[truncated to 50 chars]")
    assert "truncated" in result


@pytest.mark.asyncio
async def test_output_not_truncated_when_within_limit():
    reg = _build_registry(("srv", "small_tool"))
    mgr = _build_manager_mock("srv", call_result="short")
    settings = _build_settings(**{"limits": {"max_tool_output_chars": 100}})
    pol = _build_policies()
    router = ToolRouter(reg, mgr, settings, pol)

    result = await router.execute("srv.small_tool", {})
    assert result == "short"
