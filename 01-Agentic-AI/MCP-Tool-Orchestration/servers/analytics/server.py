"""
Analytics MCP server — create charts and dashboards from Excel files or 2-D data arrays.

No Excel installation required.  Pure Python, uses Plotly for HTML output.

Tools:
  create_chart               — single chart from 2-D data array → HTML
  create_dashboard           — 4-chart dashboard from 2-D data array → HTML
  create_chart_from_file     — single chart read directly from .xlsx (PREFERRED for Excel)
  create_dashboard_from_file — 4-chart dashboard read directly from .xlsx (PREFERRED for Excel)

Usage flow (Excel):
  1. Call excel.read_sheet_names to list sheets.
  2. Call create_dashboard_from_file(fileAbsolutePath=..., sheetName=...) — no data array needed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any

# Force UTF-8 on Windows stdin/stdout
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    def _fatal(msg: str) -> None:
        print(json.dumps({"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32000, "message": msg}}), flush=True)
        sys.exit(1)
    _fatal("plotly is not installed. Run: pip install plotly")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _default_output_path(prefix: str = "chart") -> str:
    """Return a timestamped HTML path in the user's temp folder."""
    folder = os.path.join(tempfile.gettempdir(), "mcp_analytics")
    os.makedirs(folder, exist_ok=True)
    ts = int(time.time())
    return os.path.join(folder, f"{prefix}_{ts}.html")


def _parse_data(data: Any) -> tuple[list[str], list[list[Any]]]:
    """
    Validate and split the 2-D data array.
    Returns (headers, rows) where headers is the first row and rows is the rest.
    """
    if not isinstance(data, list) or len(data) < 2:
        raise ValueError(
            "'data' must be a 2-D array with at least 2 rows "
            "(first row = headers, remaining rows = data)."
        )
    headers = [str(h) if h is not None else f"col{i}" for i, h in enumerate(data[0])]
    rows = data[1:]
    return headers, rows


def _col_values(rows: list[list[Any]], col_idx: int) -> list[Any]:
    """Extract values for one column index from all rows."""
    return [row[col_idx] if col_idx < len(row) else None for row in rows]


def _is_numeric_col(values: list[Any]) -> bool:
    """Return True if at least 60% of non-None values are numeric."""
    nums = [v for v in values if v is not None and isinstance(v, (int, float))]
    non_none = [v for v in values if v is not None]
    if not non_none:
        return False
    return len(nums) / len(non_none) >= 0.6


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _col_index(headers: list[str], col_ref: str | None, default: int) -> int:
    """
    Resolve a column reference to an integer index.
    col_ref can be a column name (string match) or a 0-based integer string.
    Falls back to `default` if None or not found.
    """
    if col_ref is None:
        return default
    # Try integer string first
    try:
        idx = int(col_ref)
        if 0 <= idx < len(headers):
            return idx
    except (ValueError, TypeError):
        pass
    # Name match (case-insensitive)
    ref_lower = col_ref.lower().strip()
    for i, h in enumerate(headers):
        if h.lower().strip() == ref_lower:
            return i
    return default


def _save_html(fig, output_path: str | None, prefix: str) -> str:
    path = output_path or _default_output_path(prefix)
    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.write_html(path, include_plotlyjs="cdn", full_html=True)
    return os.path.abspath(path)


# ── Tool: create_chart ─────────────────────────────────────────────────────────

def _create_chart(args: dict) -> str:
    chart_type: str = str(args.get("chartType", "bar")).lower().strip()
    data: Any = args["data"]
    title: str = str(args.get("title", "Chart"))
    x_col_ref: str | None = args.get("xColumn")
    y_col_ref: str | None = args.get("yColumn")
    output_path: str | None = args.get("outputPath")

    if chart_type not in ("bar", "line", "pie", "scatter"):
        raise ValueError(
            f"Unsupported chartType {chart_type!r}. Use: bar, line, pie, scatter."
        )

    headers, rows = _parse_data(data)

    # Resolve x/y column indices
    # Default: x = col 0, y = first numeric col (or col 1)
    x_idx = _col_index(headers, x_col_ref, 0)

    if y_col_ref is not None:
        y_idx = _col_index(headers, y_col_ref, 1)
    else:
        # Auto-pick first numeric column that is not x
        y_idx = 1
        for i, h in enumerate(headers):
            if i != x_idx and _is_numeric_col(_col_values(rows, i)):
                y_idx = i
                break

    x_vals = _col_values(rows, x_idx)
    y_vals = [_to_float(v) for v in _col_values(rows, y_idx)]

    if chart_type == "bar":
        fig = go.Figure(go.Bar(x=x_vals, y=y_vals, name=headers[y_idx]))
    elif chart_type == "line":
        fig = go.Figure(go.Scatter(x=x_vals, y=y_vals, mode="lines+markers", name=headers[y_idx]))
    elif chart_type == "pie":
        fig = go.Figure(go.Pie(labels=x_vals, values=y_vals, name=headers[y_idx]))
    elif chart_type == "scatter":
        fig = go.Figure(go.Scatter(x=x_vals, y=y_vals, mode="markers", name=headers[y_idx]))

    fig.update_layout(
        title_text=title,
        xaxis_title=headers[x_idx] if chart_type != "pie" else None,
        yaxis_title=headers[y_idx] if chart_type != "pie" else None,
        template="plotly_white",
    )

    saved = _save_html(fig, output_path, f"{chart_type}_chart")
    return json.dumps({
        "status": "ok",
        "chartType": chart_type,
        "title": title,
        "xColumn": headers[x_idx],
        "yColumn": headers[y_idx],
        "rowCount": len(rows),
        "outputPath": saved,
        "message": f"Chart saved to {saved}. Open this file in a browser to view it.",
    }, indent=2)


# ── Tool: create_dashboard ─────────────────────────────────────────────────────

def _create_dashboard(args: dict) -> str:
    data: Any = args["data"]
    title: str = str(args.get("title", "Dashboard"))
    output_path: str | None = args.get("outputPath")

    headers, rows = _parse_data(data)

    # Classify columns
    numeric_cols: list[int] = []
    categorical_cols: list[int] = []
    for i, h in enumerate(headers):
        vals = _col_values(rows, i)
        if _is_numeric_col(vals):
            numeric_cols.append(i)
        else:
            categorical_cols.append(i)

    if not numeric_cols:
        raise ValueError(
            "No numeric columns detected in the data. "
            "The dashboard requires at least one numeric column for charts."
        )

    # Pick columns for charts
    cat_col = categorical_cols[0] if categorical_cols else None
    num_col1 = numeric_cols[0]
    num_col2 = numeric_cols[1] if len(numeric_cols) > 1 else numeric_cols[0]

    x_vals_cat = _col_values(rows, cat_col) if cat_col is not None else list(range(1, len(rows) + 1))
    x_label_cat = headers[cat_col] if cat_col is not None else "Row"
    y_vals1 = [_to_float(v) for v in _col_values(rows, num_col1)]
    y_vals2 = [_to_float(v) for v in _col_values(rows, num_col2)]
    row_index = list(range(1, len(rows) + 1))

    # ── Aggregate by category (needed for both bar and pie) ───────────────────
    BAR_TOP_N = 20   # max bars shown
    PIE_TOP_N = 12   # max pie slices shown (rest → "Others")

    if cat_col is not None:
        agg: dict[str, float] = {}
        for lbl, v in zip(x_vals_cat, y_vals1):
            key = str(lbl) if lbl is not None else "N/A"
            agg[key] = agg.get(key, 0.0) + (v or 0.0)
        # Sort descending by value
        sorted_agg = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
        # Bar: top-N
        bar_labels = [k for k, _ in sorted_agg[:BAR_TOP_N]]
        bar_vals   = [v for _, v in sorted_agg[:BAR_TOP_N]]
        # Pie: top-N + Others
        pie_items  = sorted_agg[:PIE_TOP_N]
        others_sum = sum(v for _, v in sorted_agg[PIE_TOP_N:])
        pie_labels = [k for k, _ in pie_items]
        pie_vals   = [v for _, v in pie_items]
        if others_sum > 0:
            pie_labels.append("Others")
            pie_vals.append(others_sum)
        bar_suffix = f" (Top {BAR_TOP_N})" if len(sorted_agg) > BAR_TOP_N else ""
    else:
        bar_labels = [str(i) for i in row_index[:BAR_TOP_N]]
        bar_vals   = [v for v in y_vals1[:BAR_TOP_N] if v is not None]
        pie_labels = [str(i) for i in row_index[:PIE_TOP_N]]
        pie_vals   = [v for v in y_vals1[:PIE_TOP_N] if v is not None]
        bar_suffix = ""

    # ── Build subplots: 2×2 grid ─────────────────────────────────────────────
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            f"Bar: {x_label_cat} vs {headers[num_col1]}{bar_suffix}",
            f"Line: {headers[num_col1]} Trend",
            f"Pie: {headers[num_col1]} by {x_label_cat}",
            f"Scatter: {headers[num_col1]} vs {headers[num_col2]}",
        ),
        specs=[
            [{"type": "bar"}, {"type": "scatter"}],
            [{"type": "pie"}, {"type": "scatter"}],
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.1,
    )

    # Chart 1: Bar (top-N, sorted)
    fig.add_trace(
        go.Bar(x=bar_labels, y=bar_vals, name=headers[num_col1], showlegend=False),
        row=1, col=1,
    )

    # Chart 2: Line trend (row index × first numeric col)
    fig.add_trace(
        go.Scatter(x=row_index, y=y_vals1, mode="lines+markers",
                   name=headers[num_col1], showlegend=False),
        row=1, col=2,
    )

    # Chart 3: Pie (top-N + Others)
    fig.add_trace(
        go.Pie(
            labels=pie_labels, values=pie_vals,
            name=headers[num_col1], showlegend=False,
            textposition="inside", textinfo="percent+label",
        ),
        row=2, col=1,
    )

    # Chart 4: Scatter (num_col1 vs num_col2)
    fig.add_trace(
        go.Scatter(x=y_vals1, y=y_vals2, mode="markers",
                   name=f"{headers[num_col1]} vs {headers[num_col2]}", showlegend=False),
        row=2, col=2,
    )

    fig.update_layout(
        title_text=title,
        height=900,
        template="plotly_white",
        showlegend=False,
    )

    # Rotate bar x-axis labels so they never overlap
    fig.update_xaxes(tickangle=-45, row=1, col=1)

    saved = _save_html(fig, output_path, "dashboard")
    return json.dumps({
        "status": "ok",
        "title": title,
        "rowCount": len(rows),
        "columnCount": len(headers),
        "numericColumns": [headers[i] for i in numeric_cols],
        "categoricalColumns": [headers[i] for i in categorical_cols],
        "outputPath": saved,
        "message": f"Dashboard saved to {saved}. Open this file in a browser to view it.",
    }, indent=2)


# ── Tool: create_chart_from_file ──────────────────────────────────────────────

def _read_sheet_as_data(file_path: str, sheet_name: str | None) -> list[list[Any]]:
    """Read an xlsx sheet into a 2-D list (first row = headers)."""
    try:
        import openpyxl
    except ImportError:
        raise ValueError("openpyxl is not installed. Run: pip install openpyxl")

    wb = openpyxl.load_workbook(file_path, data_only=True)
    if sheet_name is None:
        sheet_name = wb.sheetnames[0]
    if sheet_name not in wb.sheetnames:
        raise ValueError(
            f"Sheet {sheet_name!r} not found. Available sheets: {wb.sheetnames}"
        )
    ws = wb[sheet_name]
    rows: list[list[Any]] = []
    for row in ws.iter_rows(values_only=True):
        if any(cell is not None for cell in row):
            rows.append(list(row))
    if not rows:
        raise ValueError(f"Sheet {sheet_name!r} is empty.")
    return rows


def _create_chart_from_file(args: dict) -> str:
    file_path: str = (
        args.get("fileAbsolutePath") or args.get("filePath") or ""
    ).strip()
    if not file_path:
        raise ValueError("'fileAbsolutePath' is required.")

    sheet_name: str | None = args.get("sheetName")
    chart_type: str = str(args.get("chartType", "bar")).lower().strip()
    title: str = str(args.get("title", "Chart"))
    x_col_ref: str | None = args.get("xColumn")
    y_col_ref: str | None = args.get("yColumn")
    output_path: str | None = args.get("outputPath")

    data = _read_sheet_as_data(file_path, sheet_name)
    return _create_chart({
        "chartType": chart_type,
        "data": data,
        "title": title,
        "xColumn": x_col_ref,
        "yColumn": y_col_ref,
        "outputPath": output_path,
    })


def _create_dashboard_from_file(args: dict) -> str:
    file_path: str = (
        args.get("fileAbsolutePath") or args.get("filePath") or ""
    ).strip()
    if not file_path:
        raise ValueError("'fileAbsolutePath' is required.")

    sheet_name: str | None = args.get("sheetName")
    title: str = str(args.get("title", "Dashboard"))
    output_path: str | None = args.get("outputPath")

    data = _read_sheet_as_data(file_path, sheet_name)
    return _create_dashboard({
        "data": data,
        "title": title,
        "outputPath": output_path,
    })


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_chart",
        "description": (
            "Create a single interactive chart (bar, line, pie, or scatter) from a 2-D data array "
            "and save it as a self-contained HTML file. "
            "Pass the 'rows' array from read_sheet_data directly as 'data'. "
            "First row of 'data' must be the header row. "
            "Returns the absolute path of the saved HTML file — open in any browser."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chartType": {
                    "type": "string",
                    "description": "Type of chart: 'bar', 'line', 'pie', or 'scatter'.",
                    "enum": ["bar", "line", "pie", "scatter"],
                },
                "data": {
                    "type": "array",
                    "description": (
                        "2-D array. First row = column headers, remaining rows = data values. "
                        "Example: [['Month','Sales'],['Jan',100],['Feb',150]]"
                    ),
                    "items": {"type": "array"},
                },
                "title": {
                    "type": "string",
                    "description": "Chart title (optional).",
                },
                "xColumn": {
                    "type": "string",
                    "description": "Column name or 0-based index for the X axis (optional, defaults to first column).",
                },
                "yColumn": {
                    "type": "string",
                    "description": "Column name or 0-based index for the Y axis (optional, defaults to first numeric column).",
                },
                "outputPath": {
                    "type": "string",
                    "description": "Absolute path where the HTML file will be saved (optional, defaults to temp folder).",
                },
            },
            "required": ["chartType", "data"],
        },
    },
    {
        "name": "create_dashboard",
        "description": (
            "Create a multi-chart HTML dashboard from a 2-D data array. "
            "Automatically detects numeric and categorical columns and generates "
            "a 2×2 grid with bar, line, pie, and scatter charts. "
            "Pass the 'rows' array from read_sheet_data directly as 'data'. "
            "First row of 'data' must be the header row. "
            "Returns the absolute path of the saved HTML file — open in any browser."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "description": (
                        "2-D array. First row = column headers, remaining rows = data values. "
                        "Example: [['Category','Revenue','Units'],['A',500,10],['B',300,6]]"
                    ),
                    "items": {"type": "array"},
                },
                "title": {
                    "type": "string",
                    "description": "Dashboard title (optional).",
                },
                "outputPath": {
                    "type": "string",
                    "description": "Absolute path where the HTML file will be saved (optional, defaults to temp folder).",
                },
            },
            "required": ["data"],
        },
    },
    {
        "name": "create_chart_from_file",
        "description": (
            "PREFERRED for Excel workflows. "
            "Create a single interactive chart (bar, line, pie, or scatter) by reading "
            "data directly from an Excel (.xlsx) file. No data array needed — just pass "
            "the file path and sheet name. "
            "Saves a self-contained HTML file. Returns the absolute path — open in any browser."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fileAbsolutePath": {
                    "type": "string",
                    "description": "Absolute path to the .xlsx file (e.g. C:\\Users\\...\\data.xlsx).",
                },
                "sheetName": {
                    "type": "string",
                    "description": "Sheet name to read data from. Use read_sheet_names first if unsure.",
                },
                "chartType": {
                    "type": "string",
                    "description": "Type of chart: 'bar', 'line', 'pie', or 'scatter'.",
                    "enum": ["bar", "line", "pie", "scatter"],
                },
                "title": {
                    "type": "string",
                    "description": "Chart title (optional).",
                },
                "xColumn": {
                    "type": "string",
                    "description": "Column name for the X axis (optional).",
                },
                "yColumn": {
                    "type": "string",
                    "description": "Column name for the Y axis (optional).",
                },
                "outputPath": {
                    "type": "string",
                    "description": "Absolute path to save the HTML file (optional, defaults to temp folder).",
                },
            },
            "required": ["fileAbsolutePath", "chartType"],
        },
    },
    {
        "name": "create_dashboard_from_file",
        "description": (
            "PREFERRED for Excel workflows. "
            "Create a multi-chart HTML dashboard by reading data directly from an Excel (.xlsx) file. "
            "No data array needed — just pass the file path and sheet name. "
            "Automatically detects numeric and categorical columns and generates "
            "a 2×2 grid with bar, line, pie, and scatter charts. "
            "Saves a self-contained HTML file. Returns the absolute path — open in any browser."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fileAbsolutePath": {
                    "type": "string",
                    "description": "Absolute path to the .xlsx file (e.g. C:\\Users\\...\\data.xlsx).",
                },
                "sheetName": {
                    "type": "string",
                    "description": "Sheet name to read data from. Use read_sheet_names first if unsure.",
                },
                "title": {
                    "type": "string",
                    "description": "Dashboard title (optional).",
                },
                "outputPath": {
                    "type": "string",
                    "description": "Absolute path to save the HTML file (optional, defaults to temp folder).",
                },
            },
            "required": ["fileAbsolutePath"],
        },
    },
]

_DISPATCH: dict[str, Any] = {
    "create_chart": _create_chart,
    "create_dashboard": _create_dashboard,
    "create_chart_from_file": _create_chart_from_file,
    "create_dashboard_from_file": _create_dashboard_from_file,
}


# ── MCP JSON-RPC protocol handler ──────────────────────────────────────────────

def _send(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _handle(msg: dict) -> None:
    method = msg.get("method", "")
    msg_id = msg.get("id")

    if method == "initialize":
        _send({
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "analytics-mcp-server", "version": "1.0.0"},
            },
        })

    elif method == "notifications/initialized":
        pass  # no response needed

    elif method == "tools/list":
        _send({
            "jsonrpc": "2.0", "id": msg_id,
            "result": {"tools": TOOLS},
        })

    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name: str = params.get("name", "")
        tool_args: dict = params.get("arguments", {})

        handler = _DISPATCH.get(tool_name)
        if handler is None:
            _send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Unknown tool: {tool_name!r}"}],
                    "isError": True,
                },
            })
            return

        try:
            result_text = handler(tool_args)
            _send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": result_text}]},
            })
        except (ValueError, FileNotFoundError, KeyError) as exc:
            _send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            })
        except Exception as exc:  # noqa: BLE001
            _send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Unexpected error: {exc}"}],
                    "isError": True,
                },
            })

    else:
        if msg_id is not None:
            _send({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        _handle(msg)


if __name__ == "__main__":
    main()
