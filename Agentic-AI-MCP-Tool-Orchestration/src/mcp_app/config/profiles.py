"""Profile/tag helpers for filtering server configs."""
from __future__ import annotations

from mcp_app.config.schema import MCPServersConfig, ServerConfig


def get_enabled_servers(cfg: MCPServersConfig) -> list[ServerConfig]:
    """Return only servers with enabled=True."""
    return [s for s in cfg.servers if s.enabled]


def get_servers_by_tag(cfg: MCPServersConfig, tag: str) -> list[ServerConfig]:
    """Return servers that include *tag* in their tags list."""
    return [s for s in cfg.servers if tag in s.tags]


def get_server_by_id(cfg: MCPServersConfig, server_id: str) -> ServerConfig | None:
    """Return the ServerConfig with matching id, or None."""
    for srv in cfg.servers:
        if srv.id == server_id:
            return srv
    return None
