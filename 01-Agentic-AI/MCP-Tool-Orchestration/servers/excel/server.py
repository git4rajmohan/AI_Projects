"""
Excel MCP server — read and update .xlsx / .xlsm files using openpyxl.

No Microsoft Excel installation required.  Pure Python.

Tool names match the interface expected by the orchestrator and prompting layer:

  read_sheet_names    — list all sheet names in a workbook
  read_sheet_data     — read cell values from a sheet (optional A1-style range)
  write_sheet_data    — write a 2-D data array into a range of a sheet
  read_sheet_formula  — read raw formulas from a sheet (optional range)
  write_sheet_formula — write formula strings into a range of a sheet

All tools use fileAbsolutePath and sheetName as argument names to match the
orchestrator's hint strings exactly.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

# Force UTF-8 on Windows stdin/stdout
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import openpyxl
    from openpyxl.utils import get_column_letter, column_index_from_string
except ImportError:
    def _fatal(msg: str) -> None:
        print(json.dumps({"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32000, "message": msg}}), flush=True)
        sys.exit(1)
    _fatal("openpyxl is not installed. Run: pip install openpyxl")

MAX_ROWS_HARD = int(os.environ.get("EXCEL_MAX_ROWS", "2000"))  # absolute ceiling for read operations

_ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}

# ── Safety / path helpers ──────────────────────────────────────────────────────

def _validate_workbook_path(path: str, must_exist: bool = True) -> str:
    resolved = os.path.abspath(path)
    ext = os.path.splitext(resolved)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension {ext!r}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
        )
    if must_exist and not os.path.isfile(resolved):
        raise FileNotFoundError(f"File not found: {resolved}")
    return resolved


def _cell_value(cell) -> Any:
    """Convert a cell value to a JSON-serialisable Python type."""
    val = cell.value
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


# ── A1-range parsing ───────────────────────────────────────────────────────────

_RANGE_RE = re.compile(
    r"^([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?$"
)


def _parse_range(range_str: str | None):
    """Return (min_col, min_row, max_col, max_row) or None for full sheet."""
    if not range_str:
        return None
    m = _RANGE_RE.match(range_str.strip())
    if not m:
        raise ValueError(
            f"Invalid range {range_str!r}. Use A1-style like 'A1:Z100'."
        )
    min_col = column_index_from_string(m.group(1))
    min_row = int(m.group(2))
    if m.group(3):
        max_col = column_index_from_string(m.group(3))
        max_row = int(m.group(4))
    else:
        max_col = min_col
        max_row = min_row
    return min_col, min_row, max_col, max_row


# ── Tool implementations ───────────────────────────────────────────────────────

def _read_sheet_names(args: dict) -> str:
    path = _validate_workbook_path(args["fileAbsolutePath"])
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    names = wb.sheetnames
    wb.close()
    return json.dumps(
        {"fileAbsolutePath": path, "sheetNames": names, "count": len(names)},
        indent=2,
    )


def _read_sheet_data(args: dict) -> str:
    path = _validate_workbook_path(args["fileAbsolutePath"])
    sheet_name = args["sheetName"]
    range_str: str | None = args.get("range")
    max_rows_arg = min(int(args.get("maxRows", 500)), MAX_ROWS_HARD)

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        raise ValueError(
            f"Sheet {sheet_name!r} not found. Available: {wb.sheetnames}"
        )
    ws = wb[sheet_name]

    parsed = _parse_range(range_str)
    if parsed:
        min_col, min_row, max_col, max_row = parsed
        # Clamp to max_rows_arg
        max_row = min(max_row, min_row + max_rows_arg - 1)
    else:
        min_row, min_col = 1, 1
        max_row = min((ws.max_row or 1), min_row + max_rows_arg - 1)
        max_col = None  # all columns

    rows_data: list[list[Any]] = []
    for row in ws.iter_rows(
        min_row=min_row, max_row=max_row,
        min_col=min_col, max_col=max_col,
        values_only=False,
    ):
        rows_data.append([_cell_value(c) for c in row])

    wb.close()

    total_rows = ws.max_row or 0  # already closed but value captured above
    truncated = max_row < (ws.max_row or max_row)
    result = {
        "fileAbsolutePath": path,
        "sheetName": sheet_name,
        "range": range_str or f"A1:{get_column_letter(max_col or 1)}{max_row}",
        "rows": rows_data,
        "rowCount": len(rows_data),
        "truncated": truncated,
    }
    return json.dumps(result, indent=2, default=str)


def _write_sheet_data(args: dict) -> str:
    """Write a 2-D data array into a range.  Creates sheet if it doesn't exist."""
    path = _validate_workbook_path(args["fileAbsolutePath"])
    sheet_name = args["sheetName"]
    range_str: str = args["range"]
    data: list[list[Any]] = args["data"]

    if not isinstance(data, list):
        raise ValueError("'data' must be a 2-D list of rows.")

    parsed = _parse_range(range_str)
    if not parsed:
        raise ValueError("'range' is required for write_sheet_data (e.g. 'A1:D10').")
    min_col, min_row, _max_col, _max_row = parsed

    wb = openpyxl.load_workbook(path)
    if sheet_name not in wb.sheetnames:
        wb.create_sheet(sheet_name)
    ws = wb[sheet_name]

    written = 0
    for r_offset, row_vals in enumerate(data):
        for c_offset, value in enumerate(row_vals):
            ws.cell(row=min_row + r_offset, column=min_col + c_offset, value=value)
            written += 1

    wb.save(path)
    wb.close()
    return json.dumps({
        "status": "ok",
        "sheetName": sheet_name,
        "range": range_str,
        "cellsWritten": written,
    }, indent=2)


def _read_sheet_formula(args: dict) -> str:
    """Read raw formula strings (not computed values) from a sheet."""
    path = _validate_workbook_path(args["fileAbsolutePath"])
    sheet_name = args["sheetName"]
    range_str: str | None = args.get("range")
    max_rows_arg = min(int(args.get("maxRows", 500)), MAX_ROWS_HARD)

    # data_only=False to get formula strings
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    if sheet_name not in wb.sheetnames:
        wb.close()
        raise ValueError(
            f"Sheet {sheet_name!r} not found. Available: {wb.sheetnames}"
        )
    ws = wb[sheet_name]

    parsed = _parse_range(range_str)
    if parsed:
        min_col, min_row, max_col, max_row = parsed
        max_row = min(max_row, min_row + max_rows_arg - 1)
    else:
        min_row, min_col = 1, 1
        max_row = min((ws.max_row or 1), min_row + max_rows_arg - 1)
        max_col = None

    rows_data: list[list[Any]] = []
    for row in ws.iter_rows(
        min_row=min_row, max_row=max_row,
        min_col=min_col, max_col=max_col,
        values_only=False,
    ):
        rows_data.append([c.value for c in row])

    wb.close()
    result = {
        "fileAbsolutePath": path,
        "sheetName": sheet_name,
        "range": range_str or f"A{min_row}:{get_column_letter(max_col or 1)}{max_row}",
        "formulas": rows_data,
        "rowCount": len(rows_data),
    }
    return json.dumps(result, indent=2, default=str)


def _write_sheet_formula(args: dict) -> str:
    """Write formula strings into a range.  Creates sheet if it doesn't exist."""
    path = _validate_workbook_path(args["fileAbsolutePath"])
    sheet_name = args["sheetName"]
    range_str: str = args["range"]
    formulas: list[list[Any]] = args["formulas"]

    if not isinstance(formulas, list):
        raise ValueError("'formulas' must be a 2-D list of formula strings.")

    parsed = _parse_range(range_str)
    if not parsed:
        raise ValueError("'range' is required for write_sheet_formula.")
    min_col, min_row, _mc, _mr = parsed

    wb = openpyxl.load_workbook(path)
    if sheet_name not in wb.sheetnames:
        wb.create_sheet(sheet_name)
    ws = wb[sheet_name]

    written = 0
    for r_offset, row_vals in enumerate(formulas):
        for c_offset, formula in enumerate(row_vals):
            ws.cell(row=min_row + r_offset, column=min_col + c_offset, value=formula)
            written += 1

    wb.save(path)
    wb.close()
    return json.dumps({
        "status": "ok",
        "sheetName": sheet_name,
        "range": range_str,
        "cellsWritten": written,
    }, indent=2)


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_sheet_names",
        "description": (
            "List all sheet names in an Excel workbook (.xlsx / .xlsm). "
            "Always call this first before reading or writing sheet data "
            "to discover the exact sheet names."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fileAbsolutePath": {
                    "type": "string",
                    "description": "Absolute path to the Excel (.xlsx/.xlsm) file.",
                },
            },
            "required": ["fileAbsolutePath"],
        },
    },
    {
        "name": "read_sheet_data",
        "description": (
            "Read cell values from a sheet in an Excel workbook. "
            "Returns a 2-D array of rows. "
            "Use the optional 'range' argument (A1-style, e.g. 'A1:Z200') to limit the read area. "
            "Hard limit: 2000 rows per call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fileAbsolutePath": {
                    "type": "string",
                    "description": "Absolute path to the Excel file.",
                },
                "sheetName": {
                    "type": "string",
                    "description": "Name of the sheet to read. Use read_sheet_names to discover names.",
                },
                "range": {
                    "type": "string",
                    "description": "Optional A1-style range, e.g. 'A1:Z200'. Omit to read from A1 up to the row limit.",
                },
                "maxRows": {
                    "type": "integer",
                    "description": "Maximum rows to return (default: 500, hard max: 2000).",
                },
            },
            "required": ["fileAbsolutePath", "sheetName"],
        },
    },
    {
        "name": "write_sheet_data",
        "description": (
            "Write a 2-D data array into a range of a sheet in an Excel workbook. "
            "The 'range' must cover ALL columns in your data (e.g. 'A1:L10' for 12-column data). "
            "The sheet is created automatically if it does not exist. "
            "Existing cell values in the range are overwritten. File is saved immediately."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fileAbsolutePath": {
                    "type": "string",
                    "description": "Absolute path to the Excel file.",
                },
                "sheetName": {
                    "type": "string",
                    "description": "Name of the sheet to write to. Created if it does not exist.",
                },
                "range": {
                    "type": "string",
                    "description": "A1-style range covering all columns, e.g. 'A1:D5'.",
                },
                "data": {
                    "type": "array",
                    "description": "2-D array of values. Outer array = rows, inner array = column values.",
                    "items": {"type": "array"},
                },
            },
            "required": ["fileAbsolutePath", "sheetName", "range", "data"],
        },
    },
    {
        "name": "read_sheet_formula",
        "description": (
            "Read raw formula strings (not computed values) from a sheet. "
            "Returns a 2-D array of formula strings (e.g. '=SUM(A1:A10)'). "
            "Cells without formulas return their literal value."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fileAbsolutePath": {
                    "type": "string",
                    "description": "Absolute path to the Excel file.",
                },
                "sheetName": {
                    "type": "string",
                    "description": "Name of the sheet to read.",
                },
                "range": {
                    "type": "string",
                    "description": "Optional A1-style range, e.g. 'A1:Z200'.",
                },
                "maxRows": {
                    "type": "integer",
                    "description": "Maximum rows to return (default: 500, hard max: 2000).",
                },
            },
            "required": ["fileAbsolutePath", "sheetName"],
        },
    },
    {
        "name": "write_sheet_formula",
        "description": (
            "Write formula strings into a range of a sheet. "
            "Each value should be a formula string starting with '=' (e.g. '=SUM(A1:A10)'). "
            "Non-formula strings are written as plain values. "
            "File is saved immediately."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fileAbsolutePath": {
                    "type": "string",
                    "description": "Absolute path to the Excel file.",
                },
                "sheetName": {
                    "type": "string",
                    "description": "Name of the sheet to write to. Created if it does not exist.",
                },
                "range": {
                    "type": "string",
                    "description": "A1-style range, e.g. 'B2:B10'.",
                },
                "formulas": {
                    "type": "array",
                    "description": "2-D array of formula strings. Outer = rows, inner = columns.",
                    "items": {"type": "array"},
                },
            },
            "required": ["fileAbsolutePath", "sheetName", "range", "formulas"],
        },
    },
]

_TOOL_MAP = {
    "read_sheet_names": _read_sheet_names,
    "read_sheet_data": _read_sheet_data,
    "write_sheet_data": _write_sheet_data,
    "read_sheet_formula": _read_sheet_formula,
    "write_sheet_formula": _write_sheet_formula,
}

# ── MCP JSON-RPC protocol ──────────────────────────────────────────────────────

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
            "serverInfo": {"name": "excel-mcp-python", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})

        fn = _TOOL_MAP.get(name)
        if fn is None:
            return _err(req_id, -32601, f"Unknown tool: {name!r}")

        try:
            result_text = fn(args)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            return _ok(req_id, _text(f"Error: {exc}"))
        except Exception as exc:
            return _ok(req_id, _text(f"Unexpected error: {exc}"))

        return _ok(req_id, _text(result_text))

    # Ignore other notifications (no id means notification)
    if req_id is None:
        return None

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
