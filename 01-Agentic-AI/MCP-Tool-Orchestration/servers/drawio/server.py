"""
Draw.io MCP server — generates draw.io URLs from Mermaid, CSV, or XML content.

Replicates the @drawio/mcp npm package URL generation logic in Python,
WITHOUT auto-opening the browser (the npm package always calls openBrowser()).

URL generation algorithm (matches draw.io's own compression):
  1. encodeURIComponent(content)   →  urllib.parse.quote(content, safe='')
  2. pako.deflateRaw(encoded)      →  zlib with wbits=-15 (raw DEFLATE, no header)
  3. base64(compressed)            →  base64.b64encode(...)
  4. JSON: {"type": <type>, "compressed": true, "data": <base64>}
  5. URL: https://app.diagrams.net/?grid=0&pv=0&border=10&edit=_blank#create=<url-encoded-json>
"""
from __future__ import annotations

import base64
import io
import json
import sys
import urllib.parse
import zlib

# Force UTF-8 on Windows stdin/stdout (prevents surrogate errors from cp1252)
if hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


DRAWIO_BASE = "https://app.diagrams.net/?grid=0&pv=0&border=10&edit=_blank"

import re as _re


def _sanitize_mermaid(content: str) -> str:
    """Strip constructs that draw.io's Mermaid parser doesn't support.

    - Remove classDef lines (e.g. `classDef title fill:#2c3e50,...`)
    - Remove :::className style references on nodes
    - Strip HTML tags inside node labels (e.g. ["<b>text</b>"] -> ["text"])
    - Remove %% comment lines (draw.io parser can choke on them)
    """
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        # Drop classDef definitions
        if stripped.lower().startswith("classdef "):
            continue
        # Drop %% comment lines
        if stripped.startswith("%%"):
            continue
        # Remove :::className references anywhere on the line
        line = _re.sub(r':::\w+', '', line)
        # Strip HTML tags inside node labels, keeping inner text
        line = _re.sub(r'<[^>]+>', '', line)
        lines.append(line)
    return "\n".join(lines)


def _compress(content: str) -> str:
    """Replicate pako.deflateRaw + base64 encoding."""
    # Remove any lone surrogate characters that would break UTF-8 encoding
    content = content.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    encoded = urllib.parse.quote(content, safe="")           # encodeURIComponent
    raw = zlib.compress(encoded.encode("utf-8"), level=9)    # zlib with header
    # Strip 2-byte zlib header and 4-byte adler32 checksum → raw DEFLATE
    raw_deflate = raw[2:-4]
    return base64.b64encode(raw_deflate).decode("ascii")


def _make_url(content: str, diagram_type: str, lightbox: bool = False, dark: str = "auto") -> str:
    data = _compress(content)
    payload = json.dumps({"type": diagram_type, "compressed": True, "data": data},
                         separators=(",", ":"))
    params = urllib.parse.urlencode({"grid": "0", "pv": "0", "border": "10", "edit": "_blank"})
    fragment = urllib.parse.quote(payload, safe="")
    url = f"https://app.diagrams.net/?{params}#create={fragment}"
    if lightbox:
        url = url.replace("?", "?lightbox=1&", 1)
    if dark != "auto":
        url += f"&dark={dark}"
    return url


# ── MCP Protocol ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "open_drawio_mermaid",
        "description": (
            "Generates a draw.io editor URL from Mermaid.js syntax. "
            "Supports flowcharts, sequence diagrams, class diagrams, state diagrams, "
            "entity relationship diagrams, and more. "
            "Returns a URL — present it to the user as a clickable link. "
            "Do NOT open it with browser tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Mermaid.js diagram definition."},
                "lightbox": {"type": "boolean", "description": "Read-only view mode. Default: false"},
                "dark": {"type": "string", "enum": ["auto", "true", "false"], "description": "Dark mode. Default: auto"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "open_drawio_csv",
        "description": (
            "Generates a draw.io editor URL from CSV data (org charts, flowcharts, hierarchies). "
            "Returns a URL — present it to the user as a clickable link. "
            "Do NOT open it with browser tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "CSV content in draw.io CSV import format."},
                "lightbox": {"type": "boolean", "description": "Read-only view mode. Default: false"},
                "dark": {"type": "string", "enum": ["auto", "true", "false"], "description": "Dark mode. Default: auto"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "open_drawio_xml",
        "description": (
            "Generates a draw.io editor URL from draw.io/mxGraph XML content. "
            "Returns a URL — present it to the user as a clickable link. "
            "Do NOT open it with browser tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Draw.io XML content in mxGraphModel format."},
                "lightbox": {"type": "boolean", "description": "Read-only view mode. Default: false"},
                "dark": {"type": "string", "enum": ["auto", "true", "false"], "description": "Dark mode. Default: auto"},
            },
            "required": ["content"],
        },
    },
]

TYPE_MAP = {
    "open_drawio_mermaid": "mermaid",
    "open_drawio_csv":     "csv",
    "open_drawio_xml":     "xml",
}


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _handle(request: dict):
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "drawio-mcp-python", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})

        if name not in TYPE_MAP:
            return _err(req_id, -32601, f"Unknown tool: {name}")

        content = args.get("content", "").strip()
        if not content:
            return _err(req_id, -32602, "content parameter is required")

        # Sanitize Mermaid content to remove unsupported draw.io constructs
        if TYPE_MAP[name] == "mermaid":
            content = _sanitize_mermaid(content)

        lightbox = bool(args.get("lightbox", False))
        dark = str(args.get("dark", "auto"))

        try:
            url = _make_url(content, TYPE_MAP[name], lightbox=lightbox, dark=dark)
        except Exception as exc:
            return _ok(req_id, _text(f"Error generating URL: {exc}"))

        return _ok(req_id, _text(
            f"Draw.io Editor URL:\n{url}\n\n"
            f"Click the link to open the diagram in draw.io. "
            f"If a draft dialog appears, click 'Edit' to load this diagram."
        ))

    return _err(req_id, -32601, f"Method not found: {method}")


def main():
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
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
