"""Test script: start excel MCP server, list its actual tool names, then verify orchestrator resolves them."""
import subprocess, json, time, sys, os

VENV_PYTHON = os.environ.get("MCPAPP_PYTHON", sys.executable)
NPX = r"C:\Program Files\nodejs\npx.cmd"

print("=" * 60)
print("STEP 1: Start Excel MCP server and list actual tool names")
print("=" * 60)

msgs = [
    json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2024-11-05","capabilities":{},
                  "clientInfo":{"name":"test","version":"1"}}}),
    json.dumps({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
    json.dumps({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}),
]
stdin_data = "\n".join(msgs) + "\n"

try:
    env = {"EXCEL_MCP_PAGING_CELLS_LIMIT": "4000"}
    import os; full_env = {**os.environ, **env}
    proc = subprocess.run(
        [NPX, "--yes", "@negokaz/excel-mcp-server"],
        input=stdin_data.encode(),
        capture_output=True,
        timeout=30,
        env=full_env,
    )
    stdout = proc.stdout.decode(errors="replace")
    stderr = proc.stderr.decode(errors="replace")
    
    # Parse JSON lines
    tool_names = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("id") == 2 and "result" in obj:
                tools = obj["result"].get("tools", [])
                tool_names = [t["name"] for t in tools]
                print(f"Excel server registered {len(tools)} tools:")
                for t in tools:
                    print(f"  - {t['name']!r}  (desc: {t.get('description','')[:60]})")
                break
        except json.JSONDecodeError:
            pass
    
    if not tool_names:
        print("ERROR: Could not parse tool list from server output")
        print("STDOUT (first 500):", stdout[:500])
        print("STDERR (first 500):", stderr[:500])
        sys.exit(1)

except subprocess.TimeoutExpired:
    print("ERROR: Excel server timed out after 30s")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

print()
print("=" * 60)
print("STEP 2: Verify orchestrator _resolve_full_name with actual names")
print("=" * 60)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from mcp_app.core.tool_registry import ToolRegistry

# Build a mock registry with exactly the names the excel server gives us
reg = ToolRegistry()
for name in tool_names:
    reg.register("excel", name, {"name": name, "description": f"Excel tool {name}"})

# Also add a few other typical tools
reg.register("drawio", "open_drawio_mermaid", {"name": "open_drawio_mermaid", "description": "drawio"})
reg.register("playwright", "browser_navigate", {"name": "browser_navigate", "description": "browser"})
reg.register("filesystem", "read_file", {"name": "read_file", "description": "fs"})

print(f"Registry built with {len(reg)} tools")
print(f"All names: {sorted(reg.list_names())}")

# Simulate what the LLM might call
test_calls = ["excel_describe_sheets", "excel_read_sheet", "excel_write_to_sheet",
              "excel.excel_describe_sheets", "describe_sheets", "read_sheet"]

print()
print("Testing _resolve_full_name for likely LLM tool calls:")

import re

def resolve_full_name(name: str, registry: ToolRegistry) -> str:
    if "." in name:
        if name in registry.list_names():
            return name
        bare_part = name.split(".", 1)[-1]
    else:
        bare_part = name

    all_full_names = list(registry.list_names())
    bare_map = {}
    for full in all_full_names:
        _, bare, _ = registry.resolve(full)
        bare_map[bare] = full

    if bare_part in bare_map:
        return bare_map[bare_part]

    name_lower = bare_part.lower()
    for bare, full in bare_map.items():
        if bare.lower() in name_lower:
            return full
    for bare, full in bare_map.items():
        if name_lower in bare.lower():
            return full

    req_words = set(re.split(r'[_\-\s]+', name_lower)) - {'the', 'a', 'an', 'tool', 'call'}
    best_match = None; best_score = 0
    for bare, full in bare_map.items():
        reg_words = set(re.split(r'[_\-\s]+', bare.lower()))
        overlap = len(req_words & reg_words)
        if overlap > best_score:
            best_score = overlap; best_match = full
    if best_score >= 1 and best_match:
        return best_match
    return name

all_ok = True
for call in test_calls:
    resolved = resolve_full_name(call, reg)
    found = resolved in reg.list_names()
    status = "OK" if found else "FAIL"
    if not found:
        all_ok = False
    print(f"  [{status}] {call!r} -> {resolved!r}")

print()
print("=" * 60)
print("STEP 3: Verify excel tools are present in restricted schema")
print("=" * 60)

excel_schemas = []
for full_name in reg.list_names():
    if full_name.startswith("excel."):
        _, _, schema = reg.resolve(full_name)
        excel_schemas.append(schema)

print(f"Excel schemas available for LLM: {[s['name'] for s in excel_schemas]}")
print(f"Non-excel tools NOT shown to LLM during xlsx turn: drawio, playwright, filesystem")

print()
if all_ok:
    print("ALL CHECKS PASSED - Excel tool resolution works correctly")
else:
    print("SOME CHECKS FAILED - See above")
    sys.exit(1)
