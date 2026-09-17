"""Click CLI commands: list-servers, health, list-tools."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from mcp_app.config.loader import load_all_configs
from mcp_app.config.schema import MCPServersConfig
from mcp_app.mcp.server_manager import ServerManager, ServerStatus
from mcp_app.observability.logger import get_logger

console = Console()
log = get_logger(__name__)


def _status_style(status: ServerStatus) -> str:
    styles = {
        ServerStatus.READY: "[green]READY[/green]",
        ServerStatus.STARTING: "[yellow]STARTING[/yellow]",
        ServerStatus.FAILED: "[red]FAILED[/red]",
        ServerStatus.STOPPED: "[dim]STOPPED[/dim]",
        ServerStatus.DISABLED: "[dim]DISABLED[/dim]",
    }
    return styles.get(status, str(status))


@click.command("list-servers")
@click.pass_context
def list_servers_cmd(ctx: click.Context) -> None:
    """List all configured MCP servers (from config, no connection needed)."""
    cfg: MCPServersConfig = ctx.obj["servers_cfg"]
    table = Table(title="Configured MCP Servers")
    table.add_column("ID", style="bold cyan")
    table.add_column("Name")
    table.add_column("Transport")
    table.add_column("Enabled")
    table.add_column("Tags")

    for srv in cfg.servers:
        table.add_row(
            srv.id,
            srv.name,
            srv.transport,
            "[green]yes[/green]" if srv.enabled else "[dim]no[/dim]",
            ", ".join(srv.tags) or "-",
        )

    console.print(table)
    if not cfg.servers:
        console.print("[dim]No servers configured.[/dim]")


@click.command("health")
@click.pass_context
def health_cmd(ctx: click.Context) -> None:
    """Show live health status of all enabled MCP servers."""
    cfg: MCPServersConfig = ctx.obj["servers_cfg"]
    settings = ctx.obj["settings"]

    async def _check() -> dict[str, ServerStatus]:
        async with ServerManager(cfg, app_settings=settings) as mgr:
            return mgr.all_statuses()

    try:
        statuses = asyncio.run(_check())
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        return

    table = Table(title="MCP Server Health")
    table.add_column("ID", style="bold cyan")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Error")

    for srv in cfg.servers:
        status = statuses.get(srv.id, ServerStatus.STOPPED)
        err = ""
        table.add_row(srv.id, srv.name, _status_style(status), err)

    console.print(table)


@click.command("list-tools")
@click.option("--server", "server_id", default=None, help="Filter by server id")
@click.pass_context
def list_tools_cmd(ctx: click.Context, server_id: Optional[str]) -> None:
    """List all available tools (requires starting enabled servers)."""
    cfg: MCPServersConfig = ctx.obj["servers_cfg"]
    settings = ctx.obj["settings"]

    async def _list() -> list[tuple[str, str, str]]:
        """Returns list of (server_id, tool_name, description)."""
        rows: list[tuple[str, str, str]] = []
        async with ServerManager(cfg, app_settings=settings) as mgr:
            for sid, ms in mgr.get_managed_servers().items():
                if server_id and sid != server_id:
                    continue
                if ms.status != ServerStatus.READY:
                    continue
                tools = await mgr.list_tools(sid)
                for t in tools:
                    desc = t.get("description", "")
                    rows.append((sid, t.get("name", ""), desc))
        return rows

    try:
        rows = asyncio.run(_list())
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        return

    if not rows:
        console.print("[dim]No tools available. Are servers enabled and running?[/dim]")
        return

    table = Table(title="Available Tools")
    table.add_column("Server", style="bold cyan")
    table.add_column("Tool Name", style="bold")
    table.add_column("Description")

    for sid, tname, desc in rows:
        table.add_row(sid, tname, desc or "-")

    console.print(table)
