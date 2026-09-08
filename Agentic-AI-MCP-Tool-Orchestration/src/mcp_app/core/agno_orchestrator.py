"""Agno-powered orchestrator: replaces the custom LLM + tool-call loop.

Wraps the existing ToolRegistry / ToolRouter as Agno Function tools and
delegates the full LLM + tool-call agentic loop to agno's Agent.

Preserves all custom guard logic from the original Orchestrator:
  - Excel turn detection (restrict to excel-only tools, per-turn clean slate)
  - draw.io URL capture and reply override
  - fetch_page deduplication within a turn
  - draw.io call deduplication within a turn
  - browser/playwright block during Excel turns
  - read_file block on .xlsx binary files
  - Approval gate for require_approval mode
  - MiniMax proprietary XML stripping from content
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.media import Image as AgnoImage
from agno.models.ollama import Ollama
from agno.models.openai import OpenAIChat
from agno.tools.function import Function

from mcp_app.config.schema import AppSettings, PoliciesConfig
from mcp_app.core.orchestrator import detect_xlsx_path
from mcp_app.core.session import Session, ToolCallRecord
from mcp_app.core.tool_registry import ToolRegistry
from mcp_app.core.tool_router import ToolRouter
from mcp_app.llm.prompting import build_system_message
from mcp_app.observability.logger import get_logger
from mcp_app.observability.tracing import trace_event

log = get_logger(__name__)

ApprovalCallback = Callable[[str, dict[str, Any]], bool]

# MiniMax proprietary XML strip patterns (same as openai_compat_adapter.py)
_XML_INVOKE   = re.compile(r'<invoke\b[^>]*>.*?</invoke>', re.DOTALL)
_XML_MM_CLOSE = re.compile(r'</minimax:\w+>')
_XML_MM_OPEN  = re.compile(r'<minimax:\w+[^>]*>')


def _strip_minimax_xml(text: str) -> str:
    """Strip proprietary XML tags that MiniMax leaks into content."""
    text = _XML_INVOKE.sub('', text)
    text = _XML_MM_CLOSE.sub('', text)
    text = _XML_MM_OPEN.sub('', text)
    return text.strip()


def _safe_tool_name(full_name: str) -> str:
    """Convert 'server.tool_name' to an Agno-safe identifier (a-z A-Z 0-9 _ -)."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', full_name)[:64]


class AgnoOrchestrator:
    """
    Agno-powered conversation orchestrator.

    Replaces the hand-rolled LLM+tool loop in Orchestrator with agno's
    Agent.arun(), while preserving all application-specific guard logic
    through tool-wrapper functions.

    Interface is intentionally identical to Orchestrator so ChatEngine
    needs only a one-line import change.
    """

    def __init__(
        self,
        settings: AppSettings,
        policies: PoliciesConfig,
        registry: ToolRegistry,
        router: ToolRouter,
        approval_callback: Optional[ApprovalCallback] = None,
    ) -> None:
        self._settings = settings
        self._policies = policies
        self._registry = registry
        self._router = router
        self._approval_callback = approval_callback or (lambda t, a: True)

        # Per-turn state — reset at the top of every run_turn()
        self._turn_fetched_urls: set[str] = set()
        self._turn_drawio_called: bool = False
        self._turn_has_xlsx: bool = False
        self._turn_wants_chart: bool = False
        self._turn_xlsx_path: str = ""
        self._turn_drawio_url: Optional[str] = None
        self._turn_drawio_tool_name: Optional[str] = None

        # Build tool Function objects and safe-name → full-name mapping
        self._safe_to_full: dict[str, str] = {}
        self._all_functions: list[Function] = self._build_functions()
        self._excel_functions: list[Function] = self._build_functions(excel_only=True)
        # excel + analytics tools — used when xlsx turn AND user wants charts
        self._excel_chart_functions: list[Function] = self._build_functions(
            filter_prefixes=["excel.", "analytics."]
        )

        # System prompt
        self._system_prompt: str = build_system_message("")["content"]

        # Build the Agno Agent (single instance per session)
        self._agent: Agent = self._build_agent(self._all_functions)
        # Vision agent — built lazily on first vision turn
        self._vision_agent: Optional[Agent] = None
        self._vision_build_failed: bool = False  # guard against repeated failing builds

    # ── Agent / model construction ────────────────────────────────────────────

    def _build_agent(self, tools: list[Function]) -> Agent:
        # Use StaticPool so all SQLAlchemy connections share one in-memory SQLite
        # instance — without it each pool connection gets a separate empty DB.
        _engine = create_engine(
            'sqlite://',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        _db = SqliteDb(db_engine=_engine)
        return Agent(
            model=self._make_model(),
            instructions=self._system_prompt,
            tools=tools,
            tool_call_limit=50,
            db=_db,
            add_history_to_context=True,
            num_history_runs=100,
        )

    def _make_model(self) -> Any:
        if self._settings.llm_provider == "openai_compat":
            cfg = self._settings.openai_compat
            return OpenAIChat(
                id=cfg.model,
                base_url=str(cfg.base_url),
                api_key=cfg.api_key,
                temperature=cfg.temperature,
                timeout=float(self._settings.timeouts.llm_seconds),
            )
        # Fall back to Ollama (local or cloud e.g. https://ollama.com)
        cfg_ol = self._settings.ollama
        return Ollama(
            id=cfg_ol.model,
            host=str(cfg_ol.host),
            api_key=cfg_ol.api_key or None,
            options={"temperature": cfg_ol.temperature},
        )

    def _build_vision_agent(self) -> Optional[Agent]:
        """Build a tool-free Agno Agent using the configured vision model.

        Returns None if vision is disabled or model is not set.
        """
        v = self._settings.vision
        if not v.enabled or not v.model:
            return None
        _engine = create_engine(
            'sqlite://',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        _db = SqliteDb(db_engine=_engine)
        if v.provider == "openai_compat":
            model: Any = OpenAIChat(
                id=v.model,
                base_url=str(v.base_url),
                api_key=v.api_key,
                temperature=v.temperature,
                timeout=float(self._settings.timeouts.llm_seconds),
            )
        else:
            # ponytail: reuse vision.base_url/api_key for Ollama (local or cloud
            # e.g. https://ollama.com). A non-ollama base_url (schema default) falls
            # back to the main ollama.host so a stale OpenAI URL can't be sent as host.
            _host = (
                str(v.base_url)
                if v.base_url and "ollama" in v.base_url
                else str(self._settings.ollama.host)
            )
            model = Ollama(
                id=v.model,
                host=_host,
                api_key=v.api_key or None,
                options={"temperature": v.temperature},
            )
        return Agent(
            model=model,
            instructions="You are a vision assistant. Analyse image(s) attached to the user's message and answer accurately.",
            tools=[],
            db=_db,
            add_history_to_context=True,
            num_history_runs=100,
        )

    # ── Tool building ─────────────────────────────────────────────────────────

    def _build_functions(
        self,
        excel_only: bool = False,
        filter_prefixes: list[str] | None = None,
    ) -> list[Function]:
        """Build Agno Function wrappers for registered tools.

        Args:
            excel_only:      When True, include only tools whose name starts with 'excel.'.
            filter_prefixes: When set, include only tools whose name starts with one of
                             these prefixes (takes priority over excel_only).
        """
        functions: list[Function] = []
        for full_name in self._registry.list_names():
            if filter_prefixes is not None:
                if not any(full_name.startswith(p) for p in filter_prefixes):
                    continue
            elif excel_only and not full_name.startswith("excel."):
                continue
            try:
                _, _, schema = self._registry.resolve(full_name)
            except Exception:
                continue
            fn = self._make_function(full_name, schema)
            functions.append(fn)
        return functions

    def _make_function(self, full_name: str, schema: dict) -> Function:
        """Wrap a single MCP tool as an Agno Function."""
        bare_name = full_name.split(".")[-1] if "." in full_name else full_name
        safe_name = _safe_tool_name(full_name)
        # Record mapping for post-run session tracking
        self._safe_to_full[safe_name] = full_name

        description = schema.get("description", "")
        input_schema = schema.get("inputSchema") or schema.get("parameters") or {}
        agno_params = {
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", []),
        }

        # Capture references — closure is evaluated lazily at call time
        _orch = self
        _full_name = full_name
        _bare_name = bare_name

        async def _execute(**kwargs: Any) -> str:
            return await _orch._execute_tool(_full_name, _bare_name, kwargs)

        _execute.__name__ = safe_name

        return Function(
            name=safe_name,
            description=description,
            parameters=agno_params,
            entrypoint=_execute,
            skip_entrypoint_processing=True,
        )

    # ── Tool execution (with all guard logic) ─────────────────────────────────

    async def _execute_tool(
        self,
        full_name: str,
        bare_name: str,
        args: dict[str, Any],
    ) -> str:
        """Execute one tool call with all per-turn guard logic applied."""
        mode = self._settings.tool_calling.mode

        # ── draw.io guards ────────────────────────────────────────────────────
        if bare_name in ("open_drawio_mermaid", "open_drawio_csv", "open_drawio_xml"):
            if self._turn_has_xlsx:
                log.info("BLOCKED drawio call during xlsx turn")
                return (
                    "[BLOCKED: This turn is about an Excel file. Do NOT use draw.io tools. "
                    "Use read_sheet_names → read_sheet_data → write_sheet_data.]"
                )
            if self._turn_drawio_called:
                log.info("DRAWIO: skipping duplicate %s call this turn", bare_name)
                return "[Skipped: diagram already generated this turn]"
            self._turn_drawio_called = True

        # ── browser guard during Excel turns ──────────────────────────────────
        if bare_name in ("browser_run_code", "browser_navigate") and self._turn_has_xlsx:
            return (
                f"[BLOCKED: Do NOT use browser/Playwright tools for Excel tasks. "
                f"Use: read_sheet_names(fileAbsolutePath='{self._turn_xlsx_path}'), "
                f"read_sheet_data, write_sheet_data]"
            )

        # ── read_file block on binary Excel files ─────────────────────────────
        if bare_name == "read_file":
            path = args.get("path", "") or args.get("filePath", "") or ""
            if path.lower().endswith((".xlsx", ".xls", ".xlsm", ".xltx")):
                return (
                    f"[BLOCKED: Do NOT use read_file on Excel files — binary content is unreadable. "
                    f"Use: read_sheet_names(fileAbsolutePath='{path}'), "
                    f"read_sheet_data(fileAbsolutePath='{path}', sheetName=<name>), "
                    f"write_sheet_data(...)]"
                )

        # ── fetch_page deduplication ───────────────────────────────────────────
        if bare_name == "fetch_page":
            url = args.get("url", "")
            if url and url in self._turn_fetched_urls:
                return f"[Page already fetched this turn: {url} — see earlier tool result above]"
            if url:
                self._turn_fetched_urls.add(url)

        # ── Approval gate ──────────────────────────────────────────────────────
        if mode == "require_approval":
            approved = self._approval_callback(full_name, args)
            if not approved:
                log.info("Tool call '%s' skipped by user.", full_name)
                return "[Tool call skipped by user]"

        # ── Execute via ToolRouter ─────────────────────────────────────────────
        try:
            result = await self._router.execute(full_name, args)
        except Exception as exc:
            log.error("Tool '%s' raised: %s", full_name, exc)
            return (
                f"[Tool error: {exc}] "
                f"Check the tool name and arguments. Available tools include: "
                f"{', '.join(self._registry.list_names()[:10])}..."
            )

        # ── draw.io URL capture ───────────────────────────────────────────────
        if bare_name in ("open_drawio_mermaid", "open_drawio_csv", "open_drawio_xml"):
            for line in result.splitlines():
                stripped = line.strip()
                if stripped.startswith("https://app.diagrams.net/"):
                    self._turn_drawio_url = stripped
                    self._turn_drawio_tool_name = bare_name
                    log.info("DRAWIO: captured URL from tool result")
                    break

        return result

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_turn(
        self,
        user_input: str,
        session: Session,
        system_prompt: str = "",
        images: Optional[list[str]] = None,
    ) -> str:
        """
        Process one user turn via Agno Agent and return the assistant's reply.

        Matches the Orchestrator.run_turn() interface so ChatEngine needs
        no changes beyond swapping the import.
        """
        # Reset per-turn state
        self._turn_fetched_urls = set()
        self._turn_drawio_called = False
        self._turn_drawio_url = None
        self._turn_drawio_tool_name = None

        # ── Vision model routing ──────────────────────────────────────────────
        # Route to the dedicated vision agent only when images are attached AND
        # a separate vision model is configured.  Text-only turns always use the
        # main agent so tool-calling is preserved between turns.
        # Skip if the build already failed once to avoid an infinite retry loop.
        has_images = bool(images)
        if (has_images
                and self._settings.vision.enabled
                and self._settings.vision.model
                and not self._vision_build_failed):
            return await self._run_vision_turn(user_input, images or [], session)

        return await self._run_main_agent(user_input, images, session)

    async def _run_main_agent(
        self,
        user_input: str,
        images: Optional[list[str]],
        session: Session,
    ) -> str:
        """Execute the main (tool-capable) agent and return the reply."""
        # Excel turn detection (shared quoted/UNC-safe helper)
        self._turn_xlsx_path = detect_xlsx_path(user_input)
        self._turn_has_xlsx = bool(self._turn_xlsx_path) or any(
            ext in user_input.lower() for ext in (".xlsx", ".xls", ".xlsm")
        )

        # Chart/dashboard request detection
        _chart_keywords = (
            "chart", "dashboard", "graph", "plot", "visual",
            "bar chart", "pie chart", "line chart", "scatter",
        )
        self._turn_wants_chart = any(kw in user_input.lower() for kw in _chart_keywords)

        if self._turn_has_xlsx:
            if self._turn_wants_chart:
                log.info(
                    "EXCEL+CHART TURN detected (path=%r): using %d excel+analytics tools",
                    self._turn_xlsx_path, len(self._excel_chart_functions),
                )
            else:
                log.info(
                    "EXCEL TURN detected (path=%r): restricting to %d excel tools",
                    self._turn_xlsx_path, len(self._excel_functions),
                )

        trace_event(
            "llm_request",
            {
                "model": self._settings.active_model,
                "n_messages": len(session.messages),
                "excel_turn": self._turn_has_xlsx,
                "wants_chart": self._turn_wants_chart,
            },
            session_id=session.session_id,
        )

        # Switch tools and build augmented user_input for Excel/chart turns
        augmented_input = user_input
        if self._turn_has_xlsx:
            _p = self._turn_xlsx_path or "the Excel file"
            if self._turn_wants_chart:
                self._agent.set_tools(self._excel_chart_functions)
                augmented_input = (
                    f"[CHART TASK] Read the Excel file and create a chart/dashboard.\n"
                    f"IMPORTANT: Use create_dashboard_from_file or create_chart_from_file — "
                    f"do NOT pass data arrays.\n"
                    f"Steps:\n"
                    f"  1. read_sheet_names(fileAbsolutePath={_p!r})\n"
                    f"  2. create_dashboard_from_file(fileAbsolutePath={_p!r}, "
                    f"sheetName=<first sheet>, title='Dashboard')\n"
                    f"Original request: {user_input}"
                )
            else:
                self._agent.set_tools(self._excel_functions)

        # Decode images for the main agent (vision-capable models like llava, minicpm-v)
        agno_images: list[AgnoImage] | None = None
        if images:
            import base64 as _b64
            decoded: list[AgnoImage] = []
            for b64_str in images:
                try:
                    decoded.append(AgnoImage(content=_b64.b64decode(b64_str)))
                except Exception as exc:
                    log.warning("Could not decode image for main agent: %s", exc)
            agno_images = decoded or None

        try:
            result = await self._agent.arun(
                augmented_input,
                images=agno_images,
                session_id=session.session_id,
                stream=False,
            )
        except Exception as exc:
            log.error("Agno agent.arun() failed: %s", exc)
            return f"[Error: {exc}]"
        finally:
            # Always restore full tools after Excel turn
            if self._turn_has_xlsx:
                self._agent.set_tools(self._all_functions)

        # Strip MiniMax proprietary XML from the response
        raw_content = _strip_minimax_xml(result.content or "")
        final_text = raw_content

        # Override reply with draw.io URL if a diagram was generated
        if self._turn_drawio_url:
            diagram_label = {
                "open_drawio_mermaid": "diagram",
                "open_drawio_csv": "diagram",
                "open_drawio_xml": "diagram",
            }.get(self._turn_drawio_tool_name or "", "diagram")
            final_text = (
                f"Here is your {diagram_label}: "
                f"[Open in draw.io]({self._turn_drawio_url})\n\n"
                "Click the link, then click **Edit** on the draft dialog to load the diagram."
            )
            # Keep the LLM's own commentary instead of discarding it
            if raw_content.strip():
                final_text += f"\n\n{raw_content.strip()}"
            log.info("DRAWIO: replaced Agno reply with URL-first format")

        # Update our Session (used by UI for display and tool-call panel)
        session.add_message(
            "user", user_input,
            metadata={"images": images} if images else None,
        )

        if result.tools:
            for te in result.tools:
                safe_nm = te.tool_name or ""
                full_nm = self._safe_to_full.get(safe_nm, safe_nm.replace("_", ".", 1))
                rec: ToolCallRecord = session.add_tool_call(
                    full_nm, te.tool_args or {}
                )
                rec.finish(result=str(te.result) if te.result is not None else None)

        session.add_message("assistant", final_text)

        trace_event(
            "llm_final_response",
            {"content_length": len(final_text)},
            session_id=session.session_id,
        )

        return final_text

    async def _run_vision_turn(
        self,
        user_input: str,
        images: list[str],
        session: Session,
    ) -> str:
        """Delegate an image-bearing turn to the dedicated vision model."""
        import base64

        if self._vision_agent is None and not self._vision_build_failed:
            try:
                self._vision_agent = self._build_vision_agent()
            except Exception as exc:
                log.error("Failed to build vision agent: %s", exc)
                self._vision_build_failed = True

        if self._vision_agent is None:
            log.warning(
                "Vision agent not available — falling back to main model. "
                "Check VISION_MODEL / VISION_API_KEY settings."
            )
            # Fall through directly to the main agent path (no re-entry into run_turn
            # to avoid infinite recursion now that vision routes all turns).
            self._vision_build_failed = True
            return await self._run_main_agent(user_input, images, session)

        log.info("VISION TURN: routing to vision model %r", self._settings.vision.model)

        agno_images: list[AgnoImage] = []
        for b64_str in images:
            try:
                agno_images.append(AgnoImage(content=base64.b64decode(b64_str)))
            except Exception as exc:
                log.warning("Could not decode image for vision turn: %s", exc)

        try:
            result = await self._vision_agent.arun(
                user_input,
                images=agno_images if agno_images else None,
                session_id=session.session_id,
                stream=False,
            )
        except Exception as exc:
            log.error("Vision agent.arun() failed: %s", exc)
            return f"[Vision model error: {exc}]"

        raw_content = result.content or ""
        final_text = _strip_minimax_xml(raw_content)

        session.add_message(
            "user", user_input,
            metadata={"images": images},
        )
        session.add_message("assistant", final_text)

        trace_event(
            "llm_final_response",
            {"content_length": len(final_text), "vision_turn": True},
            session_id=session.session_id,
        )

        return final_text
