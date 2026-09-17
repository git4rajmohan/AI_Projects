#!/usr/bin/env python3
"""
Playwright Enhanced MCP Server.

Provides a single high-level tool:

    pw_run_session(steps, screenshots_dir?)

The tool drives a Chromium browser through a declarative list of steps,
maintains a shared execution state across all steps, and returns a
structured JSON summary containing:

  - steps          : status + result for every requested step
  - extracted_data : title, headings, paragraphs extracted via evaluate()
  - screenshots    : list of saved screenshot absolute paths
  - network_logs   : sampled request URLs logged during the session
  - errors         : soft errors captured without stopping execution

Steps supported (step["action"] values):
  navigate      → url                 go to a URL
  click         → selector            click an element
  type          → selector, text      fill an input
  evaluate      → expression          run JS in page, store result
  extract       →                     snapshot title / h1-h3 / first paragraphs
  screenshot    → filename?           take a screenshot, return the path
  scroll        → selector? / pixels  scroll page or element
  wait          → ms                  wait N milliseconds
  snapshot      →                     return page accessibility snapshot text
  wait_for      → selector, timeout?  wait for element to appear

Execution is resilient: individual step failures are captured in `errors`
and execution continues to the next step.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

# ── Python ≥ 3.11 on Windows: default to WindowsSelectorEventLoop which is
#    asyncio-compatible, but Playwright async requires ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "pw_run_session",
        "description": (
            "Drive a Chromium browser through a sequence of steps and return a "
            "structured JSON summary. Each step has an 'action' and optional args. "
            "The session never aborts on errors — failures are captured and execution "
            "continues. Extracted data (title, headings, paragraphs), screenshots "
            "(absolute paths), network requests, and errors are all collected and "
            "returned in the final JSON report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": (
                        "Ordered list of browser steps. Each step is an object with "
                        "an 'action' key and action-specific arguments:\n"
                        "  navigate    : url (string)\n"
                        "  click       : selector (string)\n"
                        "  type        : selector (string), text (string)\n"
                        "  evaluate    : expression (string of JS, e.g. 'document.title')\n"
                        "  extract     : (no extra args) — captures title, headings, paragraphs\n"
                        "  screenshot  : filename (optional string, default: step_N.png)\n"
                        "  scroll      : selector (optional), pixels (optional int, default 500)\n"
                        "  wait        : ms (int milliseconds, default 1000)\n"
                        "  snapshot    : (no args) — returns accessibility tree text\n"
                        "  wait_for    : selector (string), timeout (optional int ms, default 5000)\n"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "navigate", "click", "type", "evaluate",
                                    "extract", "screenshot", "scroll", "wait",
                                    "snapshot", "wait_for",
                                ],
                            },
                        },
                        "required": ["action"],
                    },
                },
                "screenshots_dir": {
                    "type": "string",
                    "description": (
                        "Absolute path to save screenshots. "
                        "Defaults to current working directory."
                    ),
                },
                "headless": {
                    "type": "boolean",
                    "description": "Run headless (default true).",
                },
            },
            "required": ["steps"],
        },
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


# ── Session runner ─────────────────────────────────────────────────────────────

async def _run_session(steps: list[dict], screenshots_dir: str, headless: bool) -> dict:
    """Execute all steps and return the structured result dict."""
    from playwright.async_api import async_playwright

    Path(screenshots_dir).mkdir(parents=True, exist_ok=True)

    state: dict[str, Any] = {
        "steps": [],
        "extracted_data": {},
        "screenshots": [],
        "network_logs": [],
        "errors": [],
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # ── Network logging (non-blocking) ────────────────────────────────────
        def _on_request(req) -> None:
            state["network_logs"].append({
                "type": "request",
                "method": req.method,
                "url": req.url,
            })

        def _on_request_failed(req) -> None:
            state["errors"].append({
                "source": "network",
                "message": f"Request failed: {req.method} {req.url}",
            })

        def _on_page_error(exc) -> None:
            state["errors"].append({
                "source": "page_error",
                "message": str(exc),
            })

        page.on("request", _on_request)
        page.on("requestfailed", _on_request_failed)
        page.on("pageerror", _on_page_error)

        # ── Step execution ────────────────────────────────────────────────────
        for idx, step in enumerate(steps):
            action = step.get("action", "").strip().lower()
            step_record: dict[str, Any] = {
                "index": idx,
                "action": action,
                "status": "ok",
                "result": None,
            }

            try:
                if action == "navigate":
                    url = step.get("url", "")
                    await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    step_record["result"] = f"Navigated to: {url}"

                elif action == "click":
                    sel = step.get("selector", "")
                    await page.click(sel, timeout=10_000)
                    step_record["result"] = f"Clicked: {sel}"

                elif action == "type":
                    sel = step.get("selector", "")
                    text = step.get("text", "")
                    await page.fill(sel, text, timeout=10_000)
                    step_record["result"] = f"Typed into {sel}: {text!r}"

                elif action == "evaluate":
                    expr = step.get("expression", "")
                    val = await page.evaluate(expr)
                    step_record["result"] = val
                    # Store named results in extracted_data
                    label = step.get("label") or f"evaluate_{idx}"
                    state["extracted_data"][label] = val

                elif action == "extract":
                    # Extract common structured data from the current page
                    extracted = await page.evaluate("""() => {
                        const title = document.title || "";
                        const h1 = Array.from(document.querySelectorAll('h1')).map(e => e.innerText.trim()).filter(Boolean).slice(0, 5);
                        const h2 = Array.from(document.querySelectorAll('h2')).map(e => e.innerText.trim()).filter(Boolean).slice(0, 10);
                        const h3 = Array.from(document.querySelectorAll('h3')).map(e => e.innerText.trim()).filter(Boolean).slice(0, 10);
                        const paras = Array.from(document.querySelectorAll('p')).map(e => e.innerText.trim()).filter(Boolean).slice(0, 10);
                        const url = window.location.href;
                        return {title, h1, h2, h3, paragraphs: paras, url};
                    }""")
                    state["extracted_data"].update(extracted)
                    step_record["result"] = {
                        "title": extracted.get("title", ""),
                        "h1_count": len(extracted.get("h1", [])),
                        "h2_count": len(extracted.get("h2", [])),
                        "para_count": len(extracted.get("paragraphs", [])),
                    }

                elif action == "screenshot":
                    filename = step.get("filename") or f"step_{idx}.png"
                    if not filename.endswith(".png"):
                        filename += ".png"
                    path = str(Path(screenshots_dir) / filename)
                    await page.screenshot(path=path, full_page=False)
                    state["screenshots"].append(path)
                    step_record["result"] = f"Screenshot saved: {path}"

                elif action == "scroll":
                    sel = step.get("selector", "")
                    pixels = int(step.get("pixels", 500))
                    if sel:
                        await page.evaluate(
                            f"document.querySelector('{sel}')?.scrollBy(0, {pixels})"
                        )
                        step_record["result"] = f"Scrolled element {sel!r} by {pixels}px"
                    else:
                        await page.evaluate(f"window.scrollBy(0, {pixels})")
                        step_record["result"] = f"Scrolled window by {pixels}px"

                elif action == "wait":
                    ms = int(step.get("ms", 1000))
                    await asyncio.sleep(ms / 1000)
                    step_record["result"] = f"Waited {ms}ms"

                elif action == "snapshot":
                    snap = await page.accessibility.snapshot()
                    text = json.dumps(snap, indent=2) if snap else "(empty snapshot)"
                    # Truncate to avoid blowing token budget
                    step_record["result"] = text[:4000] + ("…" if len(text) > 4000 else "")

                elif action == "wait_for":
                    sel = step.get("selector", "")
                    timeout = int(step.get("timeout", 5000))
                    await page.wait_for_selector(sel, timeout=timeout)
                    step_record["result"] = f"Element {sel!r} appeared"

                else:
                    step_record["status"] = "skipped"
                    step_record["result"] = f"Unknown action: {action!r}"

            except Exception as exc:  # noqa: BLE001 — intentional catch-all
                step_record["status"] = "error"
                step_record["result"] = str(exc)
                state["errors"].append({
                    "source": f"step_{idx}_{action}",
                    "message": str(exc),
                    "traceback": traceback.format_exc()[-500:],
                })

            state["steps"].append(step_record)

        await browser.close()

    # Trim network_logs to most recent 50 to keep output manageable
    state["network_logs"] = state["network_logs"][-50:]
    return state


# ── MCP protocol handler ───────────────────────────────────────────────────────

def _handle(request: dict) -> dict | None:
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "playwright-enhanced-mcp", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})

        if name != "pw_run_session":
            return _err(req_id, -32601, f"Unknown tool: {name}")

        steps = args.get("steps")
        if not steps or not isinstance(steps, list):
            return _err(req_id, -32602, "'steps' must be a non-empty array")

        screenshots_dir = args.get("screenshots_dir") or os.getcwd()
        headless = bool(args.get("headless", True))

        try:
            result = asyncio.run(_run_session(steps, screenshots_dir, headless))
        except Exception as exc:  # noqa: BLE001
            result = {
                "steps": [],
                "extracted_data": {},
                "screenshots": [],
                "network_logs": [],
                "errors": [{"source": "session_init", "message": str(exc),
                            "traceback": traceback.format_exc()[-800:]}],
            }

        summary = json.dumps(result, indent=2, default=str)
        return _ok(req_id, _text_result(summary))

    return _err(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    # Force UTF-8 on Windows
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            print(json.dumps(_err(None, -32700, f"Parse error: {exc}")), flush=True)
            continue
        response = _handle(request)
        if response is not None:
            print(json.dumps(response, default=str), flush=True)


if __name__ == "__main__":
    main()
