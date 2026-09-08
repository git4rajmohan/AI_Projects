import subprocess, json, os

NPX = r"C:\Program Files\nodejs\npx.cmd"
msgs = [
    json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}),
    json.dumps({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
    json.dumps({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}),
]
env = {**os.environ, "EXCEL_MCP_PAGING_CELLS_LIMIT": "4000"}
proc = subprocess.run([NPX, "--yes", "@negokaz/excel-mcp-server"],
    input=("\n".join(msgs)+"\n").encode(), capture_output=True, timeout=30, env=env)
for line in proc.stdout.decode(errors="replace").splitlines():
    try:
        obj = json.loads(line.strip())
        if obj.get("id") == 2:
            for t in obj["result"]["tools"]:
                print("TOOL:", t["name"])
                print("  DESC:", t.get("description","")[:80])
                schema = t.get("inputSchema", {})
                props = schema.get("properties", {})
                req = schema.get("required", [])
                for k, v in props.items():
                    r = " [REQUIRED]" if k in req else ""
                    desc = v.get("description","")[:70]
                    print(f"  arg: {k!r} ({v.get('type','?')}){r} - {desc}")
                print()
    except Exception as e:
        pass
