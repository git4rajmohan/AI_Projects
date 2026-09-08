"""Interactive chat REPL for mcp chat command."""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from mcp_app.config.schema import AppSettings, MCPServersConfig, PoliciesConfig
from mcp_app.core.orchestrator import Orchestrator
from mcp_app.core.session import Session
from mcp_app.core.tool_registry import ToolRegistry
from mcp_app.core.tool_router import ToolRouter
from mcp_app.llm.factory import create_llm_adapter
from mcp_app.mcp.server_manager import ServerManager, ServerStatus
from mcp_app.observability.logger import get_logger, set_session_id

console = Console()
log = get_logger(__name__)


def _approval_prompt(tool_name: str, args: dict[str, Any]) -> bool:
    """CLI approval callback: show tool + args, ask Y/N."""
    console.print(
        Panel(
            f"[bold yellow]Tool call requested:[/bold yellow] [cyan]{tool_name}[/cyan]\n"
            f"[dim]Args:[/dim] {escape(json.dumps(args, indent=2, default=str))}",
            title="[bold]Approval Required[/bold]",
            border_style="yellow",
        )
    )
    try:
        answer = input("Run this tool? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("", "y", "yes")


async def _chat_loop(
    settings: AppSettings,
    policies: PoliciesConfig,
    servers_cfg: MCPServersConfig,
) -> None:
    """Main async chat loop."""
    console.print(
        Panel(
            f"[bold green]MCP Chat[/bold green]  model=[cyan]{settings.active_model}[/cyan]  "
            f"mode=[yellow]{settings.tool_calling.mode}[/yellow]\n"
            "[dim]Type your message and press Enter. Ctrl+C or 'exit' to quit.[/dim]",
            border_style="green",
        )
    )

    session = Session(model=settings.active_model)
    set_session_id(session.session_id)
    log.info("Chat session started: %s", session.session_id)

    async with ServerManager(servers_cfg, app_settings=settings) as mgr:
        # Build tool registry
        registry = ToolRegistry()
        await registry.build(mgr)

        n_ready = sum(
            1 for ms in mgr.get_managed_servers().values()
            if ms.status == ServerStatus.READY
        )
        console.print(
            f"[dim]{n_ready} server(s) ready, {len(registry)} tool(s) available.[/dim]\n"
        )

        # Build router
        router = ToolRouter(registry, mgr, settings, policies)

        # Approval callback
        approval_cb = (
            _approval_prompt
            if settings.tool_calling.mode == "require_approval"
            else None
        )

        # Build orchestrator
        llm = create_llm_adapter(settings)
        orchestrator = Orchestrator(
            settings=settings,
            policies=policies,
            llm=llm,
            registry=registry,
            router=router,
            approval_callback=approval_cb,
        )

        # REPL loop
        while True:
            try:
                user_input = input("\n[You] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Exiting chat...[/dim]")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                console.print("[dim]Goodbye.[/dim]")
                break

            console.print("[dim]Thinking...[/dim]")
            try:
                reply = await orchestrator.run_turn(user_input, session)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]Error:[/red] {escape(str(exc))}")
                log.error("Orchestrator error: %s", exc)
                continue

            console.print(
                Panel(
                    escape(reply),
                    title="[bold blue]Assistant[/bold blue]",
                    border_style="blue",
                )
            )

    log.info(
        "Chat session ended: %s (%d messages, %d tool calls)",
        session.session_id,
        len(session.messages),
        len(session.tool_calls),
    )


@click.command("chat")
@click.pass_context
def chat_cmd(ctx: click.Context) -> None:
    """Start an interactive chat session with tool calling support."""
    settings: AppSettings = ctx.obj["settings"]
    policies: PoliciesConfig = ctx.obj["policies"]
    servers_cfg: MCPServersConfig = ctx.obj["servers_cfg"]

    try:
        asyncio.run(_chat_loop(settings, policies, servers_cfg))
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
