"""Reusable ChatEngine: wraps Orchestrator + ServerManager lifecycle.

Used by both the CLI (interactive.py) and the Streamlit UI so that
all tool-calling logic lives in one place.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from mcp_app.config.schema import AppSettings, MCPServersConfig, PoliciesConfig
from mcp_app.core.agno_orchestrator import AgnoOrchestrator
from mcp_app.core.session import Session, ToolCallRecord
from mcp_app.core.tool_registry import ToolRegistry
from mcp_app.core.tool_router import ToolRouter
from mcp_app.mcp.server_manager import ServerManager, ServerStatus
from mcp_app.observability.logger import get_logger, set_session_id

log = get_logger(__name__)

ApprovalCallback = Callable[[str, dict[str, Any]], bool]


class ChatEngine:
    """
    Manages the full lifecycle of a chat session:
      - Start/stop MCP servers
      - Build tool registry, router, and orchestrator
      - Process conversation turns

    Usage::

        engine = ChatEngine(settings, servers_cfg, policies)
        await engine.start()
        reply, tool_calls = await engine.send("What time is it?")
        await engine.stop()
    """

    def __init__(
        self,
        settings: AppSettings,
        servers_cfg: MCPServersConfig,
        policies: PoliciesConfig,
    ) -> None:
        self._settings = settings
        self._servers_cfg = servers_cfg
        self._policies = policies
        self._mgr: Optional[ServerManager] = None
        self._registry: Optional[ToolRegistry] = None
        self._orchestrator: Optional[AgnoOrchestrator] = None
        self._session: Session = Session(model=settings.active_model)
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all MCP servers and initialise the orchestrator."""
        self._mgr = ServerManager(self._servers_cfg, app_settings=self._settings)
        await self._mgr.__aenter__()

        self._registry = ToolRegistry()
        await self._registry.build(self._mgr)

        router = ToolRouter(self._registry, self._mgr, self._settings, self._policies)

        self._orchestrator = AgnoOrchestrator(
            settings=self._settings,
            policies=self._policies,
            registry=self._registry,
            router=router,
        )

        set_session_id(self._session.session_id)
        log.info("ChatEngine started, session %s", self._session.session_id)
        self._started = True

    async def stop(self) -> None:
        """Stop all servers and clean up."""
        if self._mgr:
            await self._mgr.__aexit__(None, None, None)
            self._mgr = None
        self._started = False
        log.info("ChatEngine stopped, session %s", self._session.session_id)

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def send(
        self,
        user_input: str,
        approval_callback: Optional[ApprovalCallback] = None,
        images: Optional[list[str]] = None,
    ) -> tuple[str, list[ToolCallRecord]]:
        """
        Process a user message and return ``(reply_text, tool_calls_used)``.

        Args:
            user_input:        The user's message.
            approval_callback: Optional override for the approval gate.
                               If None, the mode from settings is used.

        Returns:
            Tuple of (assistant reply string, list of ToolCallRecord for this turn).
        """
        if not self._started or self._orchestrator is None:
            raise RuntimeError("ChatEngine not started — call start() first.")

        # Override approval callback for this turn if provided
        if approval_callback is not None:
            self._orchestrator._approval_callback = approval_callback
        elif self._settings.tool_calling.mode != "require_approval":
            self._orchestrator._approval_callback = lambda t, a: True

        before = len(self._session.tool_calls)
        reply = await self._orchestrator.run_turn(user_input, self._session, images=images)
        used = list(self._session.tool_calls[before:])
        return reply, used

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def session(self) -> Session:
        return self._session

    @property
    def server_statuses(self) -> dict[str, ServerStatus]:
        if self._mgr is None:
            return {}
        return self._mgr.all_statuses()

    @property
    def tool_count(self) -> int:
        return len(self._registry) if self._registry else 0

    @property
    def ready_count(self) -> int:
        return sum(
            1 for s in self.server_statuses.values()
            if s == ServerStatus.READY
        )
