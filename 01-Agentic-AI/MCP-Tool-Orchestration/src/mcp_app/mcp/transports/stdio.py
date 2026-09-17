"""stdio transport: spawn a subprocess and communicate over stdin/stdout."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

from mcp_app.core.errors import (
    ProcessExitedError,
    ProcessStartError,
    ProcessTimeoutError,
)
from mcp_app.mcp.transports.base import BaseTransport
from mcp_app.observability.logger import get_logger

log = get_logger(__name__)


class StdioTransport(BaseTransport):
    """
    MCP transport that communicates with a subprocess over stdin/stdout.

    The protocol is newline-delimited JSON (one JSON object per line).
    stderr from the child process is captured and logged at DEBUG level.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        cwd: Optional[str] = None,
        env: dict[str, str] | None = None,
        connect_timeout: float = 10.0,
    ) -> None:
        self._command = command
        self._args = args or []
        self._cwd = cwd
        self._env: dict[str, str] = {**os.environ, **(env or {})}
        self._connect_timeout = connect_timeout
        self._process: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        cmd = [self._command] + self._args
        log.debug("StdioTransport starting: %s", cmd)
        try:
            self._process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._cwd,
                    env=self._env,
                ),
                timeout=self._connect_timeout,
            )
        except FileNotFoundError as exc:
            raise ProcessStartError(
                f"Command not found: '{self._command}'. "
                "Check that the MCP server command is installed and on PATH."
            ) from exc
        except asyncio.TimeoutError as exc:
            raise ProcessStartError(
                f"Timed out waiting for process to start: {cmd}"
            ) from exc
        except OSError as exc:
            raise ProcessStartError(f"OS error starting process {cmd}: {exc}") from exc

        # Drain stderr in background so the pipe buffer never fills
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        # Increase stdout StreamReader buffer to 16 MB.
        # The asyncio default is 64 KB which is too small for large MCP responses
        # (e.g. Playwright accessibility snapshots of complex pages like bbc.com).
        if self._process.stdout:
            self._process.stdout._limit = 16 * 1024 * 1024  # 16 MB

        log.debug("StdioTransport started, pid=%s", self._process.pid)

    async def stop(self) -> None:
        if self._process is None:
            return
        proc = self._process
        self._process = None

        # Cancel stderr drainer
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

        # Close stdin then wait
        if proc.stdin:
            try:
                proc.stdin.close()
                await proc.stdin.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("Process pid=%s did not exit cleanly, killing.", proc.pid)
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
        log.debug("StdioTransport stopped.")

    # ── Send / Receive ────────────────────────────────────────────────────────

    async def send(self, message: dict[str, Any]) -> None:
        self._assert_alive()
        assert self._process and self._process.stdin  # noqa: S101
        line = json.dumps(message, ensure_ascii=False) + "\n"
        try:
            self._process.stdin.write(line.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ProcessExitedError(
                "Transport stdin closed unexpectedly."
            ) from exc

    async def receive(self, timeout: float = 30.0) -> dict[str, Any]:
        self._assert_alive()
        assert self._process and self._process.stdout  # noqa: S101
        try:
            raw = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            raise ProcessTimeoutError(
                f"Timed out waiting for server response (timeout={timeout}s)"
            ) from exc

        if not raw:
            raise ProcessExitedError("Server process closed stdout (EOF).")

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ProcessExitedError(
                f"Server sent non-JSON line: {raw!r}"
            ) from exc

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def is_alive(self) -> bool:
        return (
            self._process is not None
            and self._process.returncode is None
        )

    def _assert_alive(self) -> None:
        if not self.is_alive:
            rc = self._process.returncode if self._process else "N/A"
            raise ProcessExitedError(
                f"Server process is not running (returncode={rc})."
            )

    async def _drain_stderr(self) -> None:
        """Background task: read stderr lines and emit as DEBUG logs."""
        assert self._process and self._process.stderr  # noqa: S101
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                log.debug("[server stderr] %s", line.decode("utf-8", errors="replace").rstrip())
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            log.debug("stderr drainer error: %s", exc)
