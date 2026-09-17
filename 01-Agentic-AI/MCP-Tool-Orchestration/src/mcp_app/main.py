"""Entry point: parse CLI arguments, load config, run command."""
from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path
from typing import Optional

import click

from mcp_app.cli.commands import health_cmd, list_servers_cmd, list_tools_cmd
from mcp_app.cli.interactive import chat_cmd
from mcp_app.config.loader import load_all_configs
from mcp_app.core.errors import ConfigError
from mcp_app.observability.logger import setup_logging
from mcp_app.observability.tracing import init_tracing
from mcp_app.storage.redact import make_redactor


@click.group()
@click.option(
    "--config-dir",
    default=None,
    envvar="MCP_APP_CONFIG_DIR",
    type=click.Path(exists=False, file_okay=False, path_type=Path),
    help="Path to config/ directory (default: auto-detected).",
)
@click.pass_context
def main(ctx: click.Context, config_dir: Optional[Path]) -> None:
    """MCP App – local Ollama + MCP server orchestrator."""
    ctx.ensure_object(dict)

    # Load configs (fail fast on invalid)
    try:
        settings, policies, servers_cfg = load_all_configs(config_dir)
    except ConfigError as exc:
        click.echo(f"[CONFIG ERROR] {exc}", err=True)
        sys.exit(1)

    # Logging
    setup_logging(
        level=settings.logging.level,
        log_dir=settings.logging.dir,
    )

    # Tracing
    redactor = make_redactor(policies.redact_keys)
    init_tracing(trace_dir=settings.logging.dir, redactor=redactor)

    # Store configs in Click context for subcommands
    ctx.obj["settings"] = settings
    ctx.obj["policies"] = policies
    ctx.obj["servers_cfg"] = servers_cfg

    # Graceful SIGINT/SIGTERM
    def _on_signal(signum: int, frame: object) -> None:
        logging.getLogger(__name__).info(
            "Signal %s received – shutting down.", signum
        )
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)


# Register subcommands
main.add_command(list_servers_cmd)
main.add_command(health_cmd)
main.add_command(list_tools_cmd)
main.add_command(chat_cmd)


if __name__ == "__main__":
    main()
