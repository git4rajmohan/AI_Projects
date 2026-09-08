"""Main orchestrator: LLM + tool-call loop with approval hooks."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Optional, Union

from mcp_app.config.schema import AppSettings, PoliciesConfig
from mcp_app.core.errors import LLMError, PolicyDeniedError, ToolNotRegisteredError
from mcp_app.core.session import Message, Session, ToolCallRecord
from mcp_app.core.tool_registry import ToolRegistry
from mcp_app.core.tool_router import ToolRouter
from mcp_app.llm.ollama_adapter import OllamaResponse
from mcp_app.llm.prompting import build_system_message, format_tool_schemas_for_ollama
from mcp_app.llm.tool_call_parser import ParsedToolCall, get_assistant_text, parse_tool_calls, parse_tool_calls_from_text
import re

from mcp_app.observability.logger import get_logger
from mcp_app.observability.tracing import trace_event

log = get_logger(__name__)

# Approval callback: given (tool_name, args) returns True to proceed, False to skip
ApprovalCallback = Callable[[str, dict[str, Any]], bool]

# Excel path extraction: quoted (spaces allowed), UNC, or plain path.
_XLSX_PATH_RE = re.compile(
    r'"([A-Za-z]:[\\/][^"]*?\.(?:xlsx|xlsm|xls|xltx|xtlm))"'
    r'|(\\\\[^\s"]+?\.(?:xlsx|xlsm|xls|xltx|xtlm))'
    r'|([A-Za-z]:[\\/][^\s"\']*?\.(?:xlsx|xlsm|xls|xltx|xtlm))',
    re.IGNORECASE,
)


def detect_xlsx_path(text: str) -> str:
    """Extract an Excel file path (quoted, UNC, or plain) from user text; '' if none."""
    m = _XLSX_PATH_RE.search(text)
    if not m:
        return ""
    return next(g for g in m.groups() if g).replace("/", "\\")


class Orchestrator:
    """
    Main conversation orchestrator.

    Flow:
      1. Add user message to session
      2. Call Ollama with tools schema
      3. If tool calls requested:
           a. If mode=require_approval → call approval_callback
           b. Execute approved tools via ToolRouter
           c. Append tool results to messages
           d. Call Ollama again for final text
      4. Return assistant text

    approval_callback: injected from CLI layer so orchestrator has no UI dependency.
    """

    def __init__(
        self,
        settings: AppSettings,
        policies: PoliciesConfig,
        llm: Any,  # OllamaAdapter | OpenAICompatAdapter (duck-typed)
        registry: ToolRegistry,
        router: ToolRouter,
        approval_callback: Optional[ApprovalCallback] = None,
    ) -> None:
        self._settings = settings
        self._policies = policies
        self._llm = llm
        self._registry = registry
        self._router = router
        self._approval_callback = approval_callback or (lambda t, a: True)

    async def run_turn(
        self,
        user_input: str,
        session: Session,
        system_prompt: str = "",
        images: Optional[list[str]] = None,
    ) -> str:
        """
        Process one user turn and return the assistant's final reply.

        Args:
            user_input:    The user's message text.
            session:       Current session state (mutated in place).
            system_prompt: Optional extra context appended to the system prompt.

        Returns:
            Assistant reply string.
        """
        # Ensure system message at start of session
        if not session.messages:
            sys_msg = build_system_message(system_prompt)
            session.add_message("system", sys_msg["content"])

        session.add_message("user", user_input, metadata={"images": images} if images else None)

        # Per-turn dedup set: tracks URLs already fetched this turn to prevent repeated fetch_page calls
        self._turn_fetched_urls: set[str] = set()
        # Per-turn flag: prevent draw.io tool from being called more than once per turn
        self._turn_drawio_called: bool = False
        # Per-turn flag: user message references an Excel file — force excel tools only
        self._turn_xlsx_path: str = detect_xlsx_path(user_input)
        self._turn_has_xlsx: bool = bool(self._turn_xlsx_path) or any(
            ext in user_input.lower() for ext in (".xlsx", ".xls", ".xlsm")
        )
        if self._turn_has_xlsx:
            excel_tool_names = [n for n in self._registry.list_names() if 'excel' in n.lower()]
            all_tool_names = sorted(self._registry.list_names())
            log.info(
                "EXCEL TURN detected (path=%r): registry has %d total tools, %d excel tools: %r",
                self._turn_xlsx_path, len(all_tool_names), len(excel_tool_names), excel_tool_names
            )

        # Build tool schemas for LLM
        # For Excel turns: restrict to ONLY excel tools (+ analytics when chart/dashboard requested)
        _chart_keywords = ("chart", "dashboard", "graph", "plot", "visual", "bar chart", "pie chart", "line chart", "scatter")
        self._turn_wants_chart: bool = any(kw in user_input.lower() for kw in _chart_keywords)
        if self._turn_has_xlsx:
            excel_schemas = []
            for full_name in self._registry.list_names():
                include = full_name.startswith("excel.")
                if self._turn_wants_chart and full_name.startswith("analytics."):
                    include = True
                if include:
                    _, _, schema = self._registry.resolve(full_name)
                    excel_schemas.append(schema)
            ollama_tools = format_tool_schemas_for_ollama(excel_schemas) if excel_schemas else None
            log.info("EXCEL TURN: restricting LLM to %d tools (chart=%s): %r", len(excel_schemas), self._turn_wants_chart, [s.get('name') for s in excel_schemas])
        else:
            all_tools = self._registry.get_all_tools()
            ollama_tools = format_tool_schemas_for_ollama(all_tools) if all_tools else None

        # First LLM call
        # For Excel turns: use a CLEAN context (bypass any accumulated broken session history).
        # Previous failed attempts may have stacked bad tool messages that corrupt Ollama's parser.
        # Capture session size BEFORE this turn so we can isolate only new tool messages later.
        _xlsx_session_offset = len(session.to_ollama_messages())
        if self._turn_has_xlsx:
            _p = self._turn_xlsx_path or "the Excel file"
            if self._turn_wants_chart:
                xlsx_hint = (
                    f"[TASK CONTEXT - EXCEL + DASHBOARD] The user wants to read an Excel file and create a chart/dashboard.\n"
                    f"Follow these steps in order:\n"
                    f"  Step 1: read_sheet_names   fileAbsolutePath={_p}\n"
                    f"  Step 2: read_sheet_data    fileAbsolutePath={_p}, sheetName=<from step1>\n"
                    f"  Step 3: create_dashboard   data=<rows array from step2>, title=<descriptive title>\n"
                    f"          OR: create_chart   chartType=bar|line|pie|scatter, data=<rows from step2>, title=...\n"
                    f"OPTIONAL: write_sheet_data  fileAbsolutePath={_p}, sheetName=..., range=..., data=... "
                    f"(if user also wants to save processed data back to Excel)\n"
                    f"CRITICAL RULES:\n"
                    f"  - Pass the 'rows' array from read_sheet_data DIRECTLY as the 'data' argument.\n"
                    f"  - The first row of the data array must be the header row.\n"
                    f"  - create_dashboard auto-detects numeric/categorical columns — no column selection needed.\n"
                    f"  - After create_dashboard/create_chart succeeds, tell the user the outputPath to open in a browser.\n"
                    f"EXACT tool names: read_sheet_names, read_sheet_data, write_sheet_data, create_dashboard, create_chart.\n"
                    f"Do NOT call excel_describe_sheets, excel_read_sheet, excel_write_to_sheet - those do not exist.\n"
                    f"NEVER use playwright, browser_run_code, drawio, or read_file for this task."
                )
            else:
                xlsx_hint = (
                    f"[TASK CONTEXT - EXCEL FILE] The user is asking about an Excel file ({_p}). "
                    f"You MUST use ONLY these tools in this order - no other tools are allowed:\n"
                    f"  Step 1: read_sheet_names   fileAbsolutePath={_p}\n"
                    f"  Step 2: read_sheet_data    fileAbsolutePath={_p}, sheetName=<from step1>\n"
                    f"  Step 3: write_sheet_data   fileAbsolutePath={_p}, sheetName=TVdata, "
                    f"range=A1:<LastCol><N> (use ALL columns, e.g. A1:L10 for 12-col data), "
                    f"data=[[header row], [TV row1], [TV row2], ...]\n"
                    f"CRITICAL RULES:\n"
                    f"  - NEVER write Python/pandas/openpyxl code. Call the write_sheet_data tool directly.\n"
                    f"  - If data result is truncated, use the TV rows you already found and call write_sheet_data now.\n"
                    f"  - Include the header row as first element of data array.\n"
                    f"  - range width must match the number of columns in data.\n"
                    f"EXACT tool names: read_sheet_names, read_sheet_data, write_sheet_data. "
                    f"Do NOT call excel_describe_sheets, excel_read_sheet, excel_write_to_sheet - those do not exist. "
                    f"NEVER use playwright, browser_run_code, drawio, or read_file for this task."
                )
            # Clean slate: system prompt + hint + just this turn's user message
            sys_content = build_system_message(system_prompt)["content"]
            messages = [
                {"role": "system", "content": sys_content},
                {"role": "system", "content": xlsx_hint},
                {"role": "user", "content": user_input},
            ]
            log.info("EXCEL TURN: using clean message context (%d msgs), bypassing %d accumulated session msgs",
                     len(messages), len(session.to_ollama_messages()))
            # _xlsx_messages tracks the FULL context for this turn's tool rounds
            _xlsx_messages: list[dict] = list(messages)
        else:
            messages = session.to_ollama_messages()
            _xlsx_messages = []
        trace_event(
            "llm_request",
            {"model": self._settings.active_model, "n_messages": len(messages)},
            session_id=session.session_id,
        )

        try:
            response: OllamaResponse = await self._llm.chat(messages, tools=ollama_tools)
        except LLMError as exc:
            log.error("LLM call failed: %s", exc)
            return f"[Error: {exc}]"

        trace_event(
            "llm_response",
            {
                "model": response.model,
                "has_tool_calls": response.has_tool_calls,
                "content_length": len(response.content),
            },
            session_id=session.session_id,
        )

        # Agentic loop: keep calling tools as long as the LLM requests them
        MAX_TOOL_ROUNDS = self._settings.limits.max_tool_rounds  # config: limits.max_tool_rounds
        tool_round = 0

        # Track draw.io tool results so we can override LLM hallucinations
        _drawio_url: str | None = None
        _drawio_tool_name: str | None = None

        # Also detect text-based tool calls (model outputs JSON in text instead of structured calls)
        _text_calls = parse_tool_calls_from_text(response.content) if not response.has_tool_calls else []

        while (response.has_tool_calls or _text_calls) and tool_round < MAX_TOOL_ROUNDS:
            tool_round += 1
            tool_calls = parse_tool_calls(response.raw) if response.has_tool_calls else _text_calls

            # Deduplicate identical tool calls in same round (some models repeat the same call several times)
            _seen_calls: set[str] = set()
            _unique_calls: list[ParsedToolCall] = []
            for _tc in tool_calls:
                _key = f"{_tc.full_name}:{json.dumps(_tc.args, sort_keys=True)}"
                if _key not in _seen_calls:
                    _seen_calls.add(_key)
                    _unique_calls.append(_tc)
            if len(_unique_calls) < len(tool_calls):
                log.info("Deduplicated %d → %d tool calls (removed %d duplicates)",
                         len(tool_calls), len(_unique_calls), len(tool_calls) - len(_unique_calls))
            tool_calls = _unique_calls

            # Add assistant message (may contain partial text + pending tool calls).
            # Store raw tool_calls in metadata so OpenAI-compat APIs receive the
            # correct assistant message structure in follow-up turns.
            session.messages.append(
                Message(
                    role="assistant",
                    content=response.content or "",
                    metadata={"tool_calls": response.tool_calls} if response.tool_calls else {},
                )
            )

            tool_results = await self._execute_tool_calls(tool_calls, session)

            if not tool_results:
                # All tools were denied or failed — stop looping
                return response.content or "[No tool results available]"

            # Check if a draw.io tool was called — capture the FIRST URL only
            for tc, result in tool_results:
                bare = tc.full_name.split(".")[-1] if "." in tc.full_name else tc.full_name
                if bare in ("open_drawio_mermaid", "open_drawio_csv", "open_drawio_xml"):
                    if _drawio_url is None:  # only capture the first successful call
                        for line in result.splitlines():
                            line = line.strip()
                            if line.startswith("https://app.diagrams.net/"):
                                _drawio_url = line
                                _drawio_tool_name = bare
                                log.info("DRAWIO: captured URL from tool result (len=%d)", len(line))
                                break
                    else:
                        log.info("DRAWIO: ignoring duplicate tool call (URL already captured)")

            # Append tool results to messages
            for tc, result in tool_results:
                session.add_message(
                    "tool",
                    result,
                    metadata={"tool_call_id": tc.call_id, "tool_name": tc.full_name},
                )

            # If ALL tool results are errors, inject a corrective user message to help LLM recover
            all_errors = all(
                ("error" in r.lower() or "isError" in r or "required" in r or "not found" in r.lower()
                 or "skipped" in r.lower() or "blocked" in r.lower())
                for _, r in tool_results
            )
            if all_errors:
                hint = self._available_tools_hint()
                correction = (
                    f"SYSTEM CORRECTION: Your last tool call failed or was wrong. "
                    f"Re-read the user's original request and use the correct tool. "
                    f"{hint}. "
                    f"For Excel/spreadsheet tasks (.xlsx files) use ONLY: read_sheet_names, read_sheet_data, write_sheet_data. "
                    f"For diagram/flowchart tasks use: open_drawio_mermaid. "
                    f"NEVER call excel_describe_sheets, excel_read_sheet, or excel_write_to_sheet — they do not exist. "
                    f"NEVER call a diagram tool for an Excel task. Try again with the correct tool and ALL required arguments."
                )
                session.add_message("user", correction)
                log.info("Injected error-recovery correction message (all tools failed this round)")

            # Next LLM call — pass tools again so it can chain further calls
            # For xlsx turns: use clean base context + only the NEW messages from this turn
            # (avoids sending the accumulated broken session history to Ollama)
            if self._turn_has_xlsx:
                new_turn_msgs = session.to_ollama_messages()[_xlsx_session_offset:]
                messages_next = list(_xlsx_messages) + list(new_turn_msgs)
                log.info("EXCEL TURN round %d: %d clean msgs + %d new turn msgs = %d total",
                         tool_round, len(_xlsx_messages), len(new_turn_msgs), len(messages_next))
            else:
                messages_next = session.to_ollama_messages()
            trace_event(
                "llm_request_with_results",
                {
                    "model": self._settings.active_model,
                    "n_messages": len(messages_next),
                    "tool_round": tool_round,
                },
                session_id=session.session_id,
            )

            try:
                response = await self._llm.chat(messages_next, tools=ollama_tools)
            except LLMError as exc:
                log.error("LLM call (round %d) failed: %s", tool_round, exc)
                return f"[Error in tool follow-up: {exc}]"

            # Re-check text fallback for next iteration
            _text_calls = parse_tool_calls_from_text(response.content) if not response.has_tool_calls else []

        # No more tool calls — return final text
        # If a draw.io tool was called, override LLM text with the correct URL-only reply
        if _drawio_url:
            diagram_label = {
                "open_drawio_mermaid": "diagram",
                "open_drawio_csv": "diagram",
                "open_drawio_xml": "diagram",
            }.get(_drawio_tool_name or "", "diagram")
            final_text = (
                f"Here is your {diagram_label}: [Open in draw.io]({_drawio_url})\n\n"
                "Click the link, then click **Edit** on the draft dialog to load the diagram."
            )
            # Keep the LLM's own commentary instead of discarding it
            if response.content and response.content.strip():
                final_text += f"\n\n{response.content.strip()}"
            log.info("DRAWIO: replaced LLM reply with URL-first format")
        else:
            final_text = response.content
        session.add_message("assistant", final_text)
        trace_event(
            "llm_final_response",
            {"content_length": len(final_text), "tool_rounds": tool_round},
            session_id=session.session_id,
        )
        return final_text

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _execute_tool_calls(
        self,
        tool_calls: list[ParsedToolCall],
        session: Session,
    ) -> list[tuple[ParsedToolCall, str]]:
        """
        Execute approved tool calls and return (call, result) pairs.
        """
        results: list[tuple[ParsedToolCall, str]] = []
        mode = self._settings.tool_calling.mode

        for tc in tool_calls:
            # Resolve namespaced name (server_id.tool_name)
            # LLM may return bare tool name; try to find it in registry
            full_name = self._resolve_full_name(tc.full_name)

            # Skip duplicate draw.io calls within the same turn
            bare_name = full_name.split(".")[-1] if "." in full_name else full_name
            if bare_name in ("open_drawio_mermaid", "open_drawio_csv", "open_drawio_xml"):
                # Block draw.io entirely when this turn is about an Excel file
                if getattr(self, "_turn_has_xlsx", False):
                    block_msg = (
                        "[BLOCKED: This turn is about an Excel file. Do NOT use draw.io tools. "
                        "Use read_sheet_names → read_sheet_data → write_sheet_data.]"
                    )
                    log.info("BLOCKED drawio call during xlsx turn")
                    results.append((tc, block_msg))
                    continue
                if self._turn_drawio_called:
                    log.info("DRAWIO: skipping duplicate %s call this turn", bare_name)
                    results.append((tc, "[Skipped: diagram already generated this turn]"))
                    continue
                self._turn_drawio_called = True

            # Approval gate
            if mode == "require_approval":
                approved = self._approval_callback(full_name, tc.args)
                if not approved:
                    log.info("Tool call '%s' skipped by user.", full_name)
                    results.append((tc, "[Tool call skipped by user]"))
                    continue

            rec: ToolCallRecord = session.add_tool_call(full_name, tc.args)
            try:
                # Intercept browser_run_code / browser_navigate used for Excel operations
                if bare_name in ("browser_run_code", "browser_navigate") and getattr(self, "_turn_has_xlsx", False):
                    redirect_msg = (
                        f"[BLOCKED: Do NOT use browser/Playwright tools for Excel tasks. "
                        f"Use the excel tools: "
                        f"read_sheet_names(fileAbsolutePath='{self._turn_xlsx_path}'), "
                        f"read_sheet_data(fileAbsolutePath='{self._turn_xlsx_path}', sheetName=<name>), "
                        f"write_sheet_data(fileAbsolutePath='{self._turn_xlsx_path}', sheetName='TVdata', range='A1:C1', data=[[...]])]"
                    )
                    log.info("BLOCKED: %s during xlsx turn", bare_name)
                    rec.finish(result=redirect_msg)
                    results.append((tc, redirect_msg))
                    continue

                # Intercept filesystem.read_file on Excel files — redirect to read_sheet_names
                bare_name = full_name.split(".")[-1] if "." in full_name else full_name
                if bare_name == "read_file":
                    read_path = tc.args.get("path", "") or tc.args.get("filePath", "") or ""
                    if read_path.lower().endswith((".xlsx", ".xls", ".xlsm", ".xltx")):
                        redirect_msg = (
                            f"[BLOCKED: Do NOT use read_file on Excel files — binary content is unreadable.] "
                            f"For Excel files, use ONLY: "
                            f"1) read_sheet_names(fileAbsolutePath='{read_path}') to list sheets, "
                            f"2) read_sheet_data(fileAbsolutePath='{read_path}', sheetName=<name>) to read data, "
                            f"3) write_sheet_data(fileAbsolutePath='{read_path}', sheetName=<name>, range='A1:C1', data=[[...]]) to write."
                        )
                        log.info("BLOCKED: read_file on xlsx '%s' — injecting redirect hint", read_path)
                        rec.finish(result=redirect_msg)
                        results.append((tc, redirect_msg))
                        continue

                # Deduplicate fetch_page calls within the same turn
                if bare_name == "fetch_page":
                    fetch_url = tc.args.get("url", "")
                    if fetch_url and fetch_url in self._turn_fetched_urls:
                        skip_msg = f"[Page already fetched this turn: {fetch_url} — see earlier tool result above]"
                        log.info("Skipping duplicate fetch_page for URL: %s", fetch_url)
                        rec.finish(result=skip_msg)
                        results.append((tc, skip_msg))
                        continue
                    if fetch_url:
                        self._turn_fetched_urls.add(fetch_url)

                result = await self._router.execute(
                    full_name, tc.args, session_id=session.session_id
                )
                rec.finish(result=result)
                results.append((tc, result))

                # Auto-chain: if this was a search_docs call, automatically
                # fetch the top result URL so the LLM gets full page content
                auto_calls = self._get_auto_chain_calls(full_name, result, tc.args)
                log.info("AUTO-CHAIN: %d calls returned for tool '%s'", len(auto_calls), full_name)
                for auto_tc in auto_calls:
                    auto_full = self._resolve_full_name(auto_tc.full_name)
                    existing = [r[0].full_name for r in results]
                    log.info("AUTO-CHAIN: checking '%s' against existing=%r", auto_full, existing)
                    if auto_full in existing:
                        log.info("AUTO-CHAIN: skipping '%s' (already in results)", auto_full)
                        continue  # avoid duplicate fetches
                    # Also skip if this fetch_page URL was already fetched earlier this turn
                    auto_bare = auto_full.split(".")[-1] if "." in auto_full else auto_full
                    if auto_bare == "fetch_page":
                        auto_url = auto_tc.args.get("url", "")
                        if auto_url and auto_url in self._turn_fetched_urls:
                            log.info("AUTO-CHAIN: skipping fetch_page (URL already fetched): %s", auto_url)
                            continue
                        if auto_url:
                            self._turn_fetched_urls.add(auto_url)
                    log.info("Auto-chaining tool: %s", auto_full)
                    auto_rec = session.add_tool_call(auto_full, auto_tc.args)
                    try:
                        auto_result = await self._router.execute(
                            auto_full, auto_tc.args, session_id=session.session_id
                        )
                        auto_rec.finish(result=auto_result)
                        results.append((auto_tc, auto_result))
                    except Exception as auto_exc:  # noqa: BLE001
                        log.warning("Auto-chain tool '%s' error: %s", auto_full, auto_exc)
                        auto_rec.finish(error=str(auto_exc))

            except (PolicyDeniedError, ToolNotRegisteredError) as exc:
                registry_names = sorted(self._registry.list_names())
                excel_in_reg = [n for n in registry_names if 'excel' in n.lower()]
                log.warning(
                    "Tool '%s' blocked: %s | registry_size=%d, excel_tools=%r, tc.full_name=%r",
                    full_name, exc, len(registry_names), excel_in_reg, tc.full_name
                )
                rec.finish(error=str(exc))
                hint = self._available_tools_hint()
                results.append((tc, f"[Tool not found: '{full_name}'. {hint}. Use ONLY these exact tool names.]"))
            except Exception as exc:  # noqa: BLE001
                log.error("Tool '%s' error: %s", full_name, exc)
                rec.finish(error=str(exc))
                results.append((tc, f"[Tool error: {exc}]"))

        return results

    def _get_auto_chain_calls(self, tool_name: str, result: str, original_args: dict) -> list[ParsedToolCall]:
        """
        Return automatically chained tool calls based on the completed tool and its result.

        Rules:
          - After search_docs with URL results: auto-call fetch_page on the first URL.
          - After search_docs with NO results: auto-retry search with a simplified query.
        """
        auto: list[ParsedToolCall] = []

        bare = tool_name.split(".")[-1] if "." in tool_name else tool_name

        log.info("AUTO-CHAIN CHECK: tool_name=%r bare=%r result_len=%d result_preview=%r",
                 tool_name, bare, len(result) if isinstance(result, str) else -1,
                 (result[:200] if isinstance(result, str) else repr(result)))

        if bare == "search_docs":
            # Try to find an AgilePoint URL in the result
            url_match = re.search(
                r'https?://(?:documentation|helpdesk)\.agilepoint\.com[^\s\]\)"]+',
                result,
            )
            log.info("AUTO-CHAIN URL CHECK: url_match=%r", url_match.group(0) if url_match else None)
            if url_match:
                url = url_match.group(0).rstrip(".,)")
                fetch_full = self._resolve_full_name("fetch_page")
                log.info("Auto-chain: fetch_page('%s') -> resolved='%s'", url, fetch_full)
                auto.append(ParsedToolCall(full_name=fetch_full, args={"url": url}))
            else:
                # No results found — auto-retry with a shorter keyword-only query
                original_query = original_args.get("query", "")
                if original_query:
                    # Strip common filler words and take first 3 meaningful words
                    stop = {"how", "to", "a", "an", "the", "what", "is", "are", "in",
                             "for", "and", "or", "of", "with", "can", "do", "does"}
                    words = [w for w in re.split(r'[\s_\-]+', original_query.lower()) if w not in stop]
                    simplified = " ".join(words[:3])
                    if simplified and simplified.lower() != original_query.lower():
                        search_full = self._resolve_full_name("search_docs")
                        log.info("Auto-chain: search_docs retry with simplified query '%s'", simplified)
                        auto.append(ParsedToolCall(full_name=search_full, args={"query": simplified}))

        return auto

    def _resolve_full_name(self, name: str) -> str:
        """
        Resolve a tool name to a fully-qualified registry name.

        Resolution order:
          1. Exact match on full name  (server_id.tool_name)
          2. Exact match on bare tool name
          3. Fuzzy: bare name is a substring of a registered bare name
          4. Fuzzy: a registered bare name is a substring of the requested name
          5. Return as-is (router will raise ToolNotRegisteredError)
        """
        if "." in name:
            # Check it actually exists; if not, strip namespace and retry
            if name in self._registry.list_names():
                return name
            bare_part = name.split(".", 1)[-1]
        else:
            bare_part = name

        all_full_names = list(self._registry.list_names())
        bare_map: dict[str, str] = {}  # bare_name -> full_name
        for full in all_full_names:
            _, bare, _ = self._registry.resolve(full)
            bare_map[bare] = full

        log.info(
            "_resolve_full_name(%r): registry_size=%d, bare_map_size=%d, bare_part=%r, in_bare_map=%s",
            name, len(all_full_names), len(bare_map), bare_part, bare_part in bare_map
        )
        if len(all_full_names) == 0:
            log.warning("_resolve_full_name called but registry is EMPTY — engine may not have started correctly")

        # 1. Exact bare match
        if bare_part in bare_map:
            return bare_map[bare_part]

        name_lower = bare_part.lower()

        # 2. Registered bare name is contained in the requested name
        #    e.g. "search_docs" in "browser_search_docs"
        for bare, full in bare_map.items():
            if bare.lower() in name_lower:
                log.info("Fuzzy tool match: '%s' -> '%s'", name, full)
                return full

        # 3. Requested name is contained in a registered bare name
        #    e.g. "search" matches "search_docs"
        for bare, full in bare_map.items():
            if name_lower in bare.lower():
                log.info("Fuzzy tool match: '%s' -> '%s'", name, full)
                return full

        # 4. Keyword overlap — share at least one meaningful word
        req_words = set(re.split(r'[_\-\s]+', name_lower)) - {'the', 'a', 'an', 'tool', 'call'}
        best_match: str | None = None
        best_score = 0
        for bare, full in bare_map.items():
            reg_words = set(re.split(r'[_\-\s]+', bare.lower()))
            overlap = len(req_words & reg_words)
            if overlap > best_score:
                best_score = overlap
                best_match = full
        if best_score >= 1 and best_match:
            log.info("Keyword tool match: '%s' -> '%s' (score=%d)", name, best_match, best_score)
            return best_match

        # Return as-is; router will raise ToolNotRegisteredError
        return name

    def _available_tools_hint(self) -> str:
        """Return a short hint listing registered tool names for LLM error messages."""
        names = sorted(self._registry.list_names())
        return "Available tools: " + ", ".join(names) if names else ""
