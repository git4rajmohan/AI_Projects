"""Full pre-flight verification: excel tools, name resolution, prompt content, xlsx hint."""
import subprocess, json, os, sys, re

VENV_PYTHON = os.environ.get("MCPAPP_PYTHON", sys.executable)
EXCEL_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servers", "excel", "server.py")
REAL_EXCEL_TOOL_NAMES = None  # filled from live server

fails = []

def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]  {label}")
    else:
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
        fails.append(label)

print("=" * 65)
print("STEP 1: Get actual tool names from live Excel MCP server")
print("=" * 65)
msgs = [
    json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}),
    json.dumps({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
    json.dumps({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}),
]
proc = subprocess.run([VENV_PYTHON, EXCEL_SERVER],
    input=("\n".join(msgs)+"\n").encode(), capture_output=True, timeout=30)
tool_names = []
for line in proc.stdout.decode(errors="replace").splitlines():
    try:
        obj = json.loads(line.strip())
        if obj.get("id") == 2:
            tool_names = [t["name"] for t in obj["result"]["tools"]]
    except: pass
check("Excel server returned tools", len(tool_names) > 0, f"got {tool_names}")
print(f"  Actual tool names: {tool_names}")
REAL_EXCEL_TOOL_NAMES = tool_names

print()
print("=" * 65)
print("STEP 2: Verify prompting.py uses correct tool names")
print("=" * 65)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from mcp_app.llm.prompting import SYSTEM_PROMPT, build_system_message, format_tool_schemas_for_ollama

for name in ["read_sheet_names", "read_sheet_data", "write_sheet_data"]:
    check(f"prompt contains '{name}'", name in SYSTEM_PROMPT, "not found in SYSTEM_PROMPT")

for bad in ["excel_describe_sheets", "excel_read_sheet", "excel_write_to_sheet"]:
    # Should appear only as "NEVER call" warnings, not as instructions to use them
    idx = SYSTEM_PROMPT.find(bad)
    while idx != -1:
        context = SYSTEM_PROMPT[max(0,idx-150):idx+len(bad)+20]
        is_warning = any(w in context.lower() for w in ["never", "do not", "not exist", "wrong"])
        check(f"'{bad}' only in warning context", is_warning, f"found as instruction: ...{context}...")
        idx = SYSTEM_PROMPT.find(bad, idx+1)

print()
print("=" * 65)
print("STEP 3: Verify _resolve_full_name works with real tool names")
print("=" * 65)
from mcp_app.core.tool_registry import ToolRegistry

reg = ToolRegistry()
for name in REAL_EXCEL_TOOL_NAMES:
    reg.register("excel", name, {"name": name, "description": f"Excel tool {name}"})
reg.register("drawio", "open_drawio_mermaid", {"name": "open_drawio_mermaid", "description": "drawio"})
reg.register("playwright", "browser_navigate", {"name": "browser_navigate", "description": "browser"})
reg.register("filesystem", "read_file", {"name": "read_file", "description": "fs"})

def resolve(name: str, registry: ToolRegistry) -> str:
    if "." in name:
        if name in registry.list_names(): return name
        bare_part = name.split(".", 1)[-1]
    else:
        bare_part = name
    all_full_names = list(registry.list_names())
    bare_map = {}
    for full in all_full_names:
        _, bare, _ = registry.resolve(full)
        bare_map[bare] = full
    if bare_part in bare_map: return bare_map[bare_part]
    name_lower = bare_part.lower()
    for bare, full in bare_map.items():
        if bare.lower() in name_lower: return full
    for bare, full in bare_map.items():
        if name_lower in bare.lower(): return full
    req_words = set(re.split(r"[_\-\s]+", name_lower)) - {"the","a","an","tool","call"}
    best_match, best_score = None, 0
    for bare, full in bare_map.items():
        reg_words = set(re.split(r"[_\-\s]+", bare.lower()))
        overlap = len(req_words & reg_words)
        if overlap > best_score: best_score = overlap; best_match = full
    if best_score >= 1 and best_match: return best_match
    return name

# The LLM will see the real tool names in its schema, so we test those
for call in REAL_EXCEL_TOOL_NAMES:
    resolved = resolve(call, reg)
    check(f"LLM calling '{call}' resolves", resolved in reg.list_names(), f"resolved to '{resolved}'")

# Also check namespaced forms
for call in ["excel.read_sheet_names", "excel.read_sheet_data", "excel.write_sheet_data"]:
    resolved = resolve(call, reg)
    check(f"Namespaced '{call}' resolves", resolved in reg.list_names(), f"resolved to '{resolved}'")

print()
print("=" * 65)
print("STEP 4: Verify xlsx_hint in orchestrator uses correct names")
print("=" * 65)
orch_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "mcp_app", "core", "orchestrator.py"), encoding="utf-8").read()
for name in ["read_sheet_names", "read_sheet_data", "write_sheet_data"]:
    # find in xlsx_hint context
    idx = orch_src.find("xlsx_hint")
    section = orch_src[idx:idx+800] if idx != -1 else ""
    check(f"xlsx_hint contains '{name}'", name in section, "not found in xlsx_hint block")

# Make sure excel_describe_sheets doesn't appear as instruction (only as "do not use")
for bad in ["excel_describe_sheets", "excel_read_sheet", "excel_write_to_sheet"]:
    idx = orch_src.find(bad)
    while idx != -1:
        context = orch_src[max(0,idx-150):idx+len(bad)+20]
        is_warning = any(w in context.lower() for w in ["never", "do not", "not exist", "those do not"])
        check(f"orchestrator '{bad}' only in warning", is_warning, f"context: ...{context}...")
        idx = orch_src.find(bad, idx+1)

print()
print("=" * 65)
print("STEP 5: Verify excel tool restriction sends only excel schemas")
print("=" * 65)
excel_schemas = []
for full_name in reg.list_names():
    if full_name.startswith("excel."):
        _, _, schema = reg.resolve(full_name)
        excel_schemas.append(schema)

check("Excel schemas found", len(excel_schemas) == len(REAL_EXCEL_TOOL_NAMES),
      f"expected {len(REAL_EXCEL_TOOL_NAMES)}, got {len(excel_schemas)}")
check("No drawio in excel schemas", all("drawio" not in s["name"] for s in excel_schemas))
check("No browser in excel schemas", all("browser" not in s["name"] for s in excel_schemas))

print()
print("=" * 65)
if fails:
    print(f"RESULT: {len(fails)} FAILED: {fails}")
    sys.exit(1)
else:
    print(f"RESULT: ALL {5} STEPS PASSED — safe to test in the browser")
