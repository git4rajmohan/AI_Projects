"""MCP server lifecycle manager: start/stop/status tracking."""
from __future__ import annotations

import asyncio
import enum
from pathlib import Path
from typing import Any, Optional

from mcp_app.config.schema import AppSettings, MCPServersConfig, ServerConfig
from mcp_app.core.errors import UnknownTransportError
from mcp_app.mcp.client import MCPClient, ToolDefinition
from mcp_app.mcp.transports.stdio import StdioTransport
from mcp_app.observability.logger import get_logger

log = get_logger(__name__)


class ServerStatus(str, enum.Enum):
    STARTING = "STARTING"
    READY = "READY"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    DISABLED = "DISABLED"


class ManagedServer:
    """Holds runtime state for a single MCP server."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.status: ServerStatus = ServerStatus.STOPPED
        self.error: Optional[str] = None
        self._transport: Optional[Any] = None
        self._client: Optional[MCPClient] = None
        self._tools: list[ToolDefinition] = []

    @property
    def client(self) -> MCPClient:
        if self._client is None:
            raise RuntimeError(
                f"Server '{self.config.id}' client not initialised."
            )
        return self._client

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._tools)


class ServerManager:
    """
    Manages all configured MCP servers.

    Usage::

        async with ServerManager(servers_config) as mgr:
            tools = await mgr.list_tools("my_server")
    """

    def __init__(self, servers_config: MCPServersConfig, app_settings: Optional[AppSettings] = None) -> None:
        self._config = servers_config
        self._app_settings = app_settings
        self._servers: dict[str, ManagedServer] = {}

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "ServerManager":
        await self.start_all()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop_all()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start all enabled servers concurrently."""
        tasks = []
        for srv_cfg in self._config.servers:
            ms = ManagedServer(srv_cfg)
            self._servers[srv_cfg.id] = ms
            if not srv_cfg.enabled:
                ms.status = ServerStatus.DISABLED
                continue
            tasks.append(self._start_server(ms))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all running servers concurrently."""
        tasks = [
            self._stop_server(ms)
            for ms in self._servers.values()
            if ms.status not in (ServerStatus.STOPPED, ServerStatus.DISABLED)
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start_server(self, server_id: str) -> None:
        """Start a specific server by id."""
        ms = self._require(server_id)
        if ms.status == ServerStatus.DISABLED:
            log.warning("Server '%s' is disabled; skipping start.", server_id)
            return
        await self._start_server(ms)

    async def stop_server(self, server_id: str) -> None:
        """Stop a specific server by id."""
        ms = self._require(server_id)
        await self._stop_server(ms)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_status(self, server_id: str) -> ServerStatus:
        return self._require(server_id).status

    def all_statuses(self) -> dict[str, ServerStatus]:
        return {sid: ms.status for sid, ms in self._servers.items()}

    def is_ready(self, server_id: str) -> bool:
        return self._servers.get(server_id, ManagedServer(
            # dummy
            ServerConfig(id=server_id, name="", enabled=False, stdio=None)
        )).status == ServerStatus.READY

    async def list_tools(self, server_id: str) -> list[ToolDefinition]:
        ms = self._require(server_id)
        if ms.status != ServerStatus.READY:
            return ms.tools  # cached or empty
        try:
            ms._tools = await ms.client.list_tools()
        except Exception as exc:  # noqa: BLE001
            log.warning("list_tools failed for '%s': %s", server_id, exc)
        return ms.tools

    async def call_tool(
        self, server_id: str, tool_name: str, args: dict[str, Any]
    ) -> Any:
        ms = self._require(server_id)
        return await ms.client.call_tool(tool_name, args)

    def get_managed_servers(self) -> dict[str, ManagedServer]:
        return dict(self._servers)

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _start_server(self, ms: ManagedServer) -> None:
        cfg = ms.config
        ms.status = ServerStatus.STARTING
        ms.error = None
        log.info("Starting server '%s' (%s)...", cfg.id, cfg.transport)

        try:
            transport = self._build_transport(cfg)
            await transport.start()
            ms._transport = transport
            ms._client = MCPClient(
                transport=transport,
                server_id=cfg.id,
                call_timeout=float(cfg.timeouts.call_seconds),
            )
            # MCP handshake: initialize → notifications/initialized
            await ms._client.initialize()
            # Pre-fetch tool list
            ms._tools = await ms._client.list_tools()
            ms.status = ServerStatus.READY
            log.info("Server '%s' is READY (%d tools).", cfg.id, len(ms._tools))
        except Exception as exc:  # noqa: BLE001
            ms.status = ServerStatus.FAILED
            err_msg = str(exc) or f"{type(exc).__name__} (no message)"
            ms.error = err_msg
            log.error("Server '%s' failed to start: %s", cfg.id, err_msg, exc_info=True)

    async def _stop_server(self, ms: ManagedServer) -> None:
        cfg = ms.config
        log.info("Stopping server '%s'...", cfg.id)
        ms.status = ServerStatus.STOPPED
        if ms._transport:
            try:
                await ms._transport.stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("Error stopping server '%s': %s", cfg.id, exc)
            ms._transport = None
            ms._client = None

    def _build_transport(self, cfg: ServerConfig) -> Any:
        if cfg.transport == "stdio":
            assert cfg.stdio is not None  # validated by schema  # noqa: S101
            args = list(cfg.stdio.args)
            cwd = cfg.stdio.cwd

            # Merge env_file vars (if specified) with inline env dict.
            # env_file takes lower precedence — inline env: keys win on conflict.
            merged_env: dict[str, str] = {}
            if cfg.stdio.env_file:
                env_path = Path(cfg.stdio.env_file)
                if env_path.is_file():
                    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                        line = raw_line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        merged_env[k.strip()] = v.strip()
                else:
                    log.warning("env_file not found for server '%s': %s", cfg.id, cfg.stdio.env_file)
            merged_env.update(cfg.stdio.env)  # inline env: overrides env_file

            # Inject row limits for excel/sql servers from app settings
            # (server subprocesses read these via os.environ at startup)
            if self._app_settings is not None:
                if "excel" in cfg.tags:
                    merged_env.setdefault("EXCEL_MAX_ROWS", str(self._app_settings.limits.excel_max_rows))
                if "sql" in cfg.tags:
                    merged_env.setdefault("SQL_MAX_ROWS", str(self._app_settings.limits.sql_max_rows))

            # Inject browser settings for servers tagged "browser" (e.g. playwright)
            if self._app_settings is not None and "browser" in cfg.tags:
                browser = self._app_settings.browser
                # Strip any flags already in yaml to avoid duplicates
                args = [
                    a for a in args
                    if not a.startswith("--headless")
                    and not a.startswith("--no-headless")
                    and not a.startswith("--output-dir")
                ]
                if browser.headless:
                    args.append("--headless")
                screenshots_dir = str(Path(browser.screenshots_dir).resolve())
                args.append(f"--output-dir={screenshots_dir}")
                Path(screenshots_dir).mkdir(parents=True, exist_ok=True)
                if cwd is None:
                    cwd = screenshots_dir
                log.debug(
                    "Browser server '%s': headless=%s, screenshots_dir=%s",
                    cfg.id, browser.headless, screenshots_dir,
                )

            return StdioTransport(
                command=cfg.stdio.command,
                args=args,
                cwd=cwd,
                env=merged_env,
                connect_timeout=float(cfg.timeouts.connect_seconds),
            )
        raise UnknownTransportError(cfg.id, cfg.transport)

    def _require(self, server_id: str) -> ManagedServer:
        ms = self._servers.get(server_id)
        if ms is None:
            raise KeyError(
                f"No server with id '{server_id}' is managed. "
                f"Known ids: {list(self._servers.keys())}"
            )
        return ms
