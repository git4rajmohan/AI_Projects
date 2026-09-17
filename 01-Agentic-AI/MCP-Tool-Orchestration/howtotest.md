# How to Test 窶・MCP App Feature Guide (AI_MCPapp02)

Manual test procedures for every feature of the MCP App UI, with ready-to-use test data.
Run the app first, then work top to bottom. Each test lists: **Steps 竊・Expected 竊・Test data**.

**Start the app**

- Double-click `mcp_app\run_app.bat` (or run it from a terminal). Wait for the browser tab at `http://localhost:8502`.
- Log output: `C:\Temp\streamlit_out.txt`.

**Start MCP servers (once per session)**

1. Sidebar 竊・**箕・・Manage Servers** 竊・click **売 Refresh** if the list is stale, then ensure all 14 toggles are ON.
2. Send any first chat message 窶・the engine starts all enabled servers on the first turn ("Starting MCP servers窶ｦ" spinner).
3. Confirm sidebar shows `泙 窶ｦ READY` for every server and `14 ready ﾂｷ N tools` at the bottom of the status block.

**Current provider config (as configured)**

- Main LLM: 笘・ｸ・Ollama Cloud ﾂｷ `gpt-oss:120b` (tool calling supported, verified)
- Vision: 笘・ｸ・Ollama Cloud ﾂｷ `glm-5.3-flash`
- Fallback cloud (Baseten): `moonshotai/Kimi-K2.6` 窶・switch via 笞呻ｸ・Settings 竊・Provider 竊・笘・ｸ・Cloud / OpenAI-compatible

---

## 1. Server management (sidebar)

**Steps**

1. Sidebar 竊・**箕・・Manage Servers**.
2. Toggle any server OFF (e.g. `jira`) 竊・config saves and engine resets (status dots go 笞ｪ *not started*).
3. Send a chat message ("hi") 竊・engine restarts with only 13 servers; the disabled one shows 笞ｫ *DISABLED*.
4. Toggle it back ON and send "hi" again 竊・it returns to 泙 READY.
5. **筐・Add Server**: ID `mock2`, Command `<VENV>\Scripts\python.exe`, Args (one per line) `.\tests\mocks\mock_mcp_server\server.py` 竊・Save 竊・toggle ON 竊・"hi".
6. **笨擾ｸ・Edit** a server (e.g. change its Name) 竊・Save 竊・Refresh.
7. **卵・・Delete** `mock2` 竊・confirm **Yes, delete**.

**Expected** 窶・Toggling/adding/editing/deleting persists to `config/mcp_servers.yaml`; status dots update after the next message; deleted server disappears from the list.

## 2. Chat + LLM provider (Ollama Cloud)

**Steps**

1. Send: `hi` 竊・friendly reply, no tool calls.
2. Sidebar header must read `笘・ｸ・Ollama Cloud ﾂｷ gpt-oss:120b` (or the model you configured).

**Expected** 窶・Reply text renders as markdown; sidebar provider/model matches config.

## 3. Tool calling 窶・each MCP server

All verified prompt竊稚ool mappings. Expected behavior: a collapsible `肌 <server>.<tool>` expander appears (open by default), followed by the final answer, plus a `Used N tool(s): 窶ｦ` footer.

| # | Prompt to paste | Server/tool exercised |
|---|-----------------|----------------------|
| 3.1 | `What time is it now?` | `time_srv.get_current_time` |
| 3.2 | `Add 17 and 25 using the mock tools, then greet Bob.` | `mock_srv.add`, `mock_srv.greet` |
| 3.3 | `Echo this: MCP testing 123` | `mock_srv.echo` |
| 3.4 | `List the sheets in the workbook at "C:\Temp\mcp_test_data\sales.xlsx" and show the first 10 rows of the Sales sheet.` | `excel.read_sheet_names`, `excel.read_sheet_data` |
| 3.5 | `List the files in .\config` | `filesystem.list_directory` |
| 3.6 | `Show a bar chart of Q1 sales: Jan 120, Feb 90, Mar 150.` | `analytics.create_chart` (writes HTML file, returns path) |
| 3.7 | `Search the AgilePoint docs for "worklist".` | `agilepoint_docs.search_docs` |
| 3.8 | `Make a flowchart diagram: Start -> Validate -> (ok) -> Process -> End; (invalid) -> Reject.` | `drawio.open_drawio_mermaid` |
| 3.9 | `Fetch https://example.com and summarize it.` | `web-fetch` tools |

**Expected** 窶・Correct tool invoked; result readable in the expander (Output column); final answer reflects the tool result.

## 4. Phase 1 窶・UI/UX checks

### 4.1 Tool-call expander defaults to OPEN

1. Trigger any tool call (e.g. test 3.1).
2. The `肌 窶ｦ` expander is expanded (contents visible) without clicking it.
3. 笞呻ｸ・Settings 竊・肌 Tool Calling 竊・**Tool Calls Expanded** OFF still keeps it expanded; toggle it ON/OFF 竊・behavior flips only when the setting is ON.

### 4.2 Errors render as red boxes

1. In 笞呻ｸ・Settings 竊・肌 Tool Calling 竊・set **Approval Mode** = `require_approval`, save.
2. Send: `What time is it now?` 竊・an approval prompt appears; **deny** it (or stop the server first: Manage Servers 竊・toggle `time_srv` OFF, then ask the same question and re-enable after).
3. The chat shows a **red error box** (`st.error`), NOT plain text like `[Error: 窶ｦ]`.
4. Also verify the error persists in history (scroll up 窶・it's still a red box).
5. Restore Approval Mode = `auto` afterward.

### 4.3 Long-output expander

1. Send: `Read rows 1 to 500 of the Sales sheet in "C:\Temp\mcp_test_data\sales.xlsx".`
2. The tool output block shows the first ~3000 characters and a **塘 View full output** expander.
3. Click it 竊・the full untruncated result appears.

### 4.4 Processing status block

1. Send: `What time is it now?` and watch while it runs.
2. A full-width **笞呻ｸ・Processing窶ｦ** status block (with spinner + **Stop** button inside) replaces the old cramped 2-column layout.
3. Click **Stop** mid-run on a slow prompt (e.g. a big file read) 竊・generation stops cleanly.

### 4.5 Settings sections

1. Open 笞呻ｸ・Settings in the sidebar.
2. Sections appear in order with icons + dividers: `### ｧ LLM`, `### 早・・Vision`, `### 肌 Tool Calling`, `### 竢ｱ・・Timeouts & Limits (s)`, `### 倹 Browser`, `### 耳 Theme`.
3. Each section is followed by a divider line.

## 5. Phase 2 窶・Robustness checks

### 5.1 Excel path regex (quoted / UNC paths)

1. Create the workbook per **Test data 8.1** (`C:\Temp\mcp_test_data\sales.xlsx`).
2. Send (quoted path with spaces 窶・note the folder name has a space): `Read the Sales sheet from "C:\Temp\mcp test data\sales.xlsx" and summarize it.`
3. Send (UNC path): `Read the Sales sheet from \\localhost\C$\Temp\mcp_test_data\sales.xlsx 窶・list its columns.`
4. Send (plain path): `Read the Sales sheet from C:\Temp\mcp_test_data\sales.xlsx.`

**Expected** 窶・In ALL three cases the Excel tool is invoked and scoped correctly (not blocked by the xlsx-turn tool restriction). Trailing quotes must not leak into the path.

### 5.2 Tool-call retry (transient errors)

1. Trigger a tool call (test 3.1). Note it succeeds.
2. Simulate a transient failure: Manage Servers 竊・toggle `time_srv` OFF 竊・ON again, then immediately ask `What time is it in Tokyo?`.
3. If the first attempt fails at the transport level, the router retries (2ﾃ・ before surfacing an error 窶・most of the time you'll just see it succeed.
4. Permanent failures (bad tool name, policy denial) should fail fast with NO retry delay.

### 5.3 Draw.io reply keeps LLM commentary

1. Send: `Make a simple flowchart diagram: A -> B -> C. Also explain what each step does in one sentence.`
2. The reply contains the **[Open in draw.io](窶ｦ)** link FIRST, followed by the model's explanation text below it.
3. Edge case: request a diagram with commentary disabled (just "make the diagram, no explanation") 竊・degrades to link-only reply.

### 5.4 Externalized limits

1. Open `config/app_settings.yaml` 竊・`limits:` shows `max_tool_rounds: 20`, `excel_max_rows: 2000`, `sql_max_rows: 500`.
2. Change `excel_max_rows: 5`, save, sidebar **売 Restart**, then send test 4.3's prompt.
3. The Excel server now caps results at 5 rows (row-cap error/notice from the tool).
4. Revert to 2000. Also verify env override works: set `env: {EXCEL_MAX_ROWS: "10"}` on the excel server in `config/mcp_servers.yaml` (Manage Servers 竊・笨擾ｸ・excel 竊・env) 竊・Restart 竊・row cap = 10. Remove afterward.

## 6. Phase 3 窶・Vision

**Steps**

1. Generate the test image per **Test data 8.2** 竊・`C:\Temp\mcp_test_data\vision_test.png`.
2. Sidebar 竊・早・・Vision section 竊・**Enable Vision** = ON (model `glm-5.3-flash`, provider `ollama`). The sidebar badge shows `早・・Vision ﾂｷ glm-5.3-flash`.
3. **梼 Upload Files** 竊・upload `vision_test.png` (or drag-drop an image into the chat).
4. Send: `What do you see in this image? Describe the shapes and any text.`

**Expected** 窶・The reply mentions the red background, the yellow circle, AND the digits `742` 窶・content only knowable from the image (i.e. the model actually saw it). The turn is routed through the vision agent (log line `VISION TURN: routing to vision model` in `./.mcp_app_logs/`).

**Negative test** 窶・Disable Vision in Settings and repeat with an image attached: the main model either answers blind (no image analysis) or errors gracefully; no crash.

## 7. CLI + test suites (regression)

**Steps (from `mcp_app/` folder, venv python)**

| Command | Expected |
|---------|----------|
| `<VENV>\Scripts\python.exe test_preflight.py` | `ALL 5 STEPS PASSED` banner (needs `PYTHONIOENCODING=utf-8` on this console) |
| `..\venv\Scripts\python.exe -m pytest mcp_app/tests/ -q` (from repo root) | `44 passed`; the 11 `test_cli_smoke.py` failures are **pre-existing** (click/CliRunner incompat) and must not change count |
| `..\venv\Scripts\python.exe test_excel_tools.py` | `ALL CHECKS PASSED` |
| `..\venv\Scripts\python.exe test_excel_schema.py` | exit code 0 |
| `mcp chat` (CLI, non-streaming contract) | Still starts, answers one turn, exits cleanly |

## 8. Test data

### 8.1 Excel workbook 窶・`C:\Temp\mcp_test_data\sales.xlsx`

**Required** 窶・no workbook exists in the repo yet. Create it (run once from `mcp_app/`):

```powershell
<VENV>\Scripts\python.exe -c "
import openpyxl, os
os.makedirs(r'C:\Temp\mcp_test_data', exist_ok=True)
wb = openpyxl.Workbook()
ws = wb.active; ws.title = 'Sales'
ws.append(['Month', 'Region', 'Product', 'Units', 'Revenue'])
rows = [
    ['Jan','East','Widget',120,14400],['Jan','West','Widget',90,10800],
    ['Feb','East','Widget',110,13200],['Feb','West','Gadget',75,15000],
    ['Mar','East','Gadget',80,16000],['Mar','West','Widget',150,18000],
    ['Apr','East','Widget',95,11400],['Apr','West','Gadget',60,12000],
    ['May','East','Widget',130,15600],['May','West','Widget',100,12000],
    ['Jun','East','Gadget',70,14000],['Jun','West','Widget',160,19200],
]
for r in rows: ws.append(r)
wb.create_sheet('Regions').append(['Region','Manager','Target'])
wb.save(r'C:\Temp\mcp_test_data\sales.xlsx')
print('created C:/Temp/mcp_test_data/sales.xlsx')
"
```

Contents: sheet **Sales** (13 rows: `Month, Region, Product, Units, Revenue`) + sheet **Regions** (header only). Good for: sheet listing, row reads, formulas, long-output truncation, chart-from-file.

Also create the **quoted-path variant** (folder with a space) used by test 5.1:

```powershell
New-Item -ItemType Directory -Force -Path 'C:\Temp\mcp test data' | Out-Null
Copy-Item 'C:\Temp\mcp_test_data\sales.xlsx' 'C:\Temp\mcp test data\sales.xlsx'
```

### 8.2 Vision test image 窶・`C:\Temp\mcp_test_data\vision_test.png`

Red background + yellow circle + white digits `742` (content verifiable only by seeing it):

```powershell
<VENV>\Scripts\python.exe -c "
from PIL import Image, ImageDraw
import os
os.makedirs(r'C:\Temp\mcp_test_data', exist_ok=True)
img = Image.new('RGB', (300, 200), (200, 30, 30))
d = ImageDraw.Draw(img)
d.ellipse([40, 40, 160, 160], fill=(250, 220, 50))
try:
    from PIL import ImageFont
    f = ImageFont.load_default(size=48)
except Exception:
    f = None
d.text((180, 70), '742', fill=(255, 255, 255), font=f)
img.save(r'C:\Temp\mcp_test_data\vision_test.png')
print('created vision_test.png')
"
```

**Pass criteria:** reply names 竕･2 of {red background, yellow circle, "742"}.

### 8.3 SQLite database for the SQL server 窶・`C:\Temp\mcp_test_data\test.db`

```powershell
<VENV>\Scripts\python.exe -c "
import sqlite3, os
os.makedirs(r'C:\Temp\mcp_test_data', exist_ok=True)
con = sqlite3.connect(r'C:\Temp\mcp_test_data\test.db')
cur = con.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY, name TEXT, dept TEXT, salary REAL)')
cur.executemany('INSERT INTO employees (name, dept, salary) VALUES (?,?,?)', [
    ('Alice','Engineering',95000),('Bob','Sales',61000),('Carol','Engineering',103000),
    ('Dave','HR',57000),('Eve','Sales',66000),('Frank','Engineering',88000)])
con.commit(); con.close()
print('created test.db')
"
```

Then: `List the tables in sqlite:///C:/Temp/mcp_test_data/test.db, then run SELECT dept, AVG(salary) FROM employees GROUP BY dept.` 竊・`sql.list_tables` + `sql.query` (result capped by `sql_max_rows`).

### 8.4 Draw.io diagram prompts (no files needed)

Paste into chat (see 3.8 / 5.3). Mermaid and CSV variants both map to `open_drawio_mermaid` / `open_drawio_csv`.

### 8.5 Chart data for analytics 窶・`C:\Temp\mcp_test_data\chart_data.xlsx`

```powershell
<VENV>\Scripts\python.exe -c "
import openpyxl, os
os.makedirs(r'C:\Temp\mcp_test_data', exist_ok=True)
wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Data'
ws.append(['Category', 'Value'])
for k, v in [('Alpha',12),('Beta',30),('Gamma',7),('Delta',22),('Epsilon',18)]: ws.append([k, v])
wb.save(r'C:\Temp\mcp_test_data\chart_data.xlsx')
print('created chart_data.xlsx')
"
```

Then: `Create a bar chart from the Data sheet of C:\Temp\mcp_test_data\chart_data.xlsx with Category as labels and Value as values.` 竊・HTML chart file path returned; open it in a browser to confirm it renders.

---

## Known pre-existing issues (not regressions)

- `tests/test_cli_smoke.py` 窶・11 failures from a `click`/`CliRunner` version incompatibility; fails identically on unmodified code.
- Windows console: `test_preflight.py` banner contains an em-dash; run with `PYTHONIOENCODING=utf-8` to avoid `UnicodeEncodeError` on cp932 consoles.
- `qwen3-vl:8b` returns 404 on Ollama Cloud (not in the cloud plan); `glm-5.3-flash` is the configured vision model.
