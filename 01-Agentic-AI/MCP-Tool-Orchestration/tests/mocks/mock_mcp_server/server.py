#!/usr/bin/env python3
"""
Minimal deterministic mock MCP server for testing.

Communicates via stdin/stdout using Newline-Delimited JSON-RPC 2.0.

Supported methods:
  - tools/list  → returns a fixed set of 3 tools
  - tools/call  → returns predictable output per tool name
  - initialize  → responds with server info (optional handshake)
"""
from __future__ import annotations

import json
import sys


TOOLS = [
    {
        "name": "echo",
        "description": "Echoes back the provided text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo"}
            },
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "Adds two numbers together.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "greet",
        "description": "Returns a greeting for the given name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name to greet"}
            },
            "required": ["name"],
        },
    },
]


def _make_result(req_id: str, result: object) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id: str, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _handle(request: dict) -> dict:
    req_id = request.get("id", "")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _make_result(req_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "mock_mcp_server", "version": "0.1.0"},
            "capabilities": {"tools": {}},
        })

    if method == "tools/list":
        return _make_result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "echo":
            text = arguments.get("text", "")
            return _make_result(req_id, {
                "content": [{"type": "text", "text": f"Echo: {text}"}]
            })

        if tool_name == "add":
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            return _make_result(req_id, {
                "content": [{"type": "text", "text": str(a + b)}]
            })

        if tool_name == "greet":
            name = arguments.get("name", "World")
            return _make_result(req_id, {
                "content": [{"type": "text", "text": f"Hello, {name}!"}]
            })

        return _make_error(req_id, -32601, f"Tool not found: {tool_name}")

    if method == "notifications/initialized":
        # Fire-and-forget notification; don't respond
        return None  # type: ignore[return-value]

    return _make_error(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            print(json.dumps(resp), flush=True)
            continue

        response = _handle(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
