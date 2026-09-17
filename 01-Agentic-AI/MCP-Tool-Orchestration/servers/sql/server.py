"""
SQL MCP server — execute SQL queries against SQLite, PostgreSQL, MySQL, or SQL Server.

Connection string formats
--------------------------
  SQLite:       sqlite:///C:/path/to/file.db   OR just  C:\\path\\to\\file.db
  PostgreSQL:   postgresql://user:password@host:5432/dbname
  MySQL:        mysql://user:password@host:3306/dbname
  SQL Server:   mssql://user:password@host/dbname

Tools
------
  sql_query          — read-only SELECT query → JSON rows
  sql_execute        — INSERT / UPDATE / DELETE / DDL → affected-row count
  sql_list_tables    — list tables and views in the database
  sql_describe_table — show column names and types for a table
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any
from urllib.parse import urlparse

# Force UTF-8 on Windows stdin/stdout (prevents cp1252 surrogate errors)
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_ROWS_HARD = int(os.environ.get("SQL_MAX_ROWS", "500"))  # absolute ceiling — never return more than this

# Regex: safe table / column name (letters, digits, underscore, dot, $, brackets)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.$\[\]\" ]+$")


# ── Connection helpers ─────────────────────────────────────────────────────────

def _parse_conn(conn_str: str):
    """
    Parse *conn_str* and return (driver_name: str, connection_object).
    Raises RuntimeError with a human-readable message on failure.
    """
    cs = conn_str.strip()

    # ── SQLite ──────────────────────────────────────────────────────────────
    if cs.lower().startswith("sqlite:///"):
        path = cs[len("sqlite:///"):]
        import sqlite3
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return "sqlite", conn

    if cs.lower().startswith("sqlite://"):
        path = cs[len("sqlite://"):]
        import sqlite3
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return "sqlite", conn

    # Bare file path: starts with drive letter, forward-slash, or ends in .db/.sqlite
    if re.match(r"^[A-Za-z]:[/\\]", cs) or cs.startswith("/") or re.search(
        r"\.(db|sqlite|sqlite3)$", cs, re.IGNORECASE
    ):
        import sqlite3
        conn = sqlite3.connect(cs)
        conn.row_factory = sqlite3.Row
        return "sqlite", conn

    # ── PostgreSQL ──────────────────────────────────────────────────────────
    if cs.lower().startswith(("postgresql://", "postgres://")):
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 is not installed. Install with: pip install psycopg2-binary"
            ) from exc
        conn = psycopg2.connect(cs)
        conn.autocommit = False
        return "postgresql", conn

    # ── MySQL ───────────────────────────────────────────────────────────────
    if cs.lower().startswith("mysql://"):
        parsed = urlparse(cs)
        kwargs = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username,
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/"),
        }
        try:
            import pymysql
            conn = pymysql.connect(**kwargs)
            return "mysql", conn
        except ImportError:
            pass
        try:
            import mysql.connector
            conn = mysql.connector.connect(**kwargs)
            return "mysql", conn
        except ImportError as exc:
            raise RuntimeError(
                "No MySQL driver found. Install: pip install pymysql"
            ) from exc

    # ── SQL Server ──────────────────────────────────────────────────────────
    if cs.lower().startswith(("mssql://", "sqlserver://")):
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError(
                "pyodbc is not installed. Install with: pip install pyodbc"
            ) from exc
        parsed = urlparse(cs)
        host = parsed.hostname or ""
        db = parsed.path.lstrip("/")
        user = parsed.username or ""
        password = parsed.password or ""
        if user:
            odbc = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={host};"
                f"DATABASE={db};"
                f"UID={user};"
                f"PWD={password};"
            )
        else:
            # Windows Integrated Authentication
            odbc = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={host};"
                f"DATABASE={db};"
                "Trusted_Connection=yes;"
            )
        conn = pyodbc.connect(odbc)
        return "mssql", conn

    raise RuntimeError(
        f"Unrecognized connection string: {cs!r}. "
        "Supported prefixes: sqlite:///, postgresql://, mysql://, mssql://"
    )


def _rows_to_list(cursor, rows) -> tuple[list[str], list[dict]]:
    """Convert raw cursor rows to (columns, list-of-dicts)."""
    if cursor.description:
        cols = [d[0] for d in cursor.description]
    else:
        cols = []
    result = []
    for row in rows:
        if hasattr(row, "keys"):
            result.append(dict(row))
        else:
            result.append(dict(zip(cols, row)))
    return cols, result


def _validate_name(name: str, label: str = "name") -> None:
    """Raise ValueError if name contains unsafe characters."""
    if not _SAFE_NAME.match(name):
        raise ValueError(
            f"Invalid {label} {name!r}. Only letters, digits, underscore, dot, $, and brackets are allowed."
        )


# ── Per-database schema helpers ────────────────────────────────────────────────

def _list_tables_impl(driver: str, conn) -> list[str]:
    cur = conn.cursor()
    if driver == "sqlite":
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view') ORDER BY name"
        )
        return [r[0] for r in cur.fetchall()]
    if driver == "postgresql":
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
            "ORDER BY table_schema, table_name"
        )
        return [r[0] for r in cur.fetchall()]
    if driver == "mysql":
        cur.execute("SHOW FULL TABLES")
        return [r[0] for r in cur.fetchall()]
    if driver == "mssql":
        cur.execute(
            "SELECT TABLE_SCHEMA + '.' + TABLE_NAME "
            "FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE IN ('BASE TABLE','VIEW') "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME"
        )
        return [r[0] for r in cur.fetchall()]
    return []


def _describe_table_impl(driver: str, conn, table_name: str) -> list[dict]:
    _validate_name(table_name, "table_name")
    cur = conn.cursor()
    if driver == "sqlite":
        # PRAGMA doesn't support parameters; name is validated above
        cur.execute(f"PRAGMA table_info(\"{table_name}\")")
        rows = cur.fetchall()
        return [
            {"cid": r[0], "name": r[1], "type": r[2],
             "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])}
            for r in rows
        ]
    if driver == "postgresql":
        cur.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = %s "
            "ORDER BY ordinal_position",
            (table_name,),
        )
        return [
            {"name": r[0], "type": r[1], "nullable": r[2], "default": r[3]}
            for r in cur.fetchall()
        ]
    if driver == "mysql":
        # table name validated; use backtick quoting
        cur.execute(f"DESCRIBE `{table_name}`")
        return [
            {"field": r[0], "type": r[1], "null": r[2],
             "key": r[3], "default": r[4], "extra": r[5]}
            for r in cur.fetchall()
        ]
    if driver == "mssql":
        cur.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            (table_name,),
        )
        return [
            {"name": r[0], "type": r[1], "nullable": r[2], "default": r[3]}
            for r in cur.fetchall()
        ]
    return []


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "sql_query",
        "description": (
            "Execute a read-only SQL query (SELECT / WITH / EXPLAIN) and return the results "
            "as a JSON object with 'columns', 'rows', 'row_count', and 'truncated' fields. "
            "Supports SQLite, PostgreSQL, MySQL, and SQL Server. "
            "Use parameterized queries (? placeholders) with the 'params' argument to avoid SQL injection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": (
                        "Database connection string. Examples: "
                        "sqlite:///C:/data/mydb.db | "
                        "postgresql://user:pass@localhost:5432/mydb | "
                        "mysql://user:pass@localhost/mydb | "
                        "mssql://user:pass@server/mydb"
                    ),
                },
                "sql": {
                    "type": "string",
                    "description": "The SELECT (or WITH/EXPLAIN) statement to execute.",
                },
                "params": {
                    "type": "array",
                    "description": "Optional list of positional parameters for ? placeholders in the query.",
                    "items": {},
                },
                "max_rows": {
                    "type": "integer",
                    "description": f"Maximum rows to return (default: 100, hard limit: {MAX_ROWS_HARD}).",
                },
            },
            "required": ["connection_string", "sql"],
        },
    },
    {
        "name": "sql_execute",
        "description": (
            "Execute an INSERT, UPDATE, DELETE, or DDL statement (CREATE, ALTER, DROP, etc.). "
            "Returns a JSON object with 'status' and 'affected_rows'. "
            "The statement is committed automatically on success."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "Database connection string (same format as sql_query).",
                },
                "sql": {
                    "type": "string",
                    "description": "The SQL statement to execute.",
                },
                "params": {
                    "type": "array",
                    "description": "Optional list of positional parameters for ? placeholders.",
                    "items": {},
                },
            },
            "required": ["connection_string", "sql"],
        },
    },
    {
        "name": "sql_list_tables",
        "description": (
            "List all tables and views in the database. "
            "Returns a JSON object with a 'tables' array."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "Database connection string.",
                },
            },
            "required": ["connection_string"],
        },
    },
    {
        "name": "sql_describe_table",
        "description": (
            "Show the column names, types, nullability, and defaults for a table. "
            "Returns a JSON object with a 'columns' array."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "Database connection string.",
                },
                "table_name": {
                    "type": "string",
                    "description": "Name of the table to describe.",
                },
            },
            "required": ["connection_string", "table_name"],
        },
    },
]


# ── MCP protocol helpers ───────────────────────────────────────────────────────

def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


# ── Tool handlers ──────────────────────────────────────────────────────────────

# Words allowed at the start of a sql_query statement
_READONLY_PREFIXES = {"SELECT", "WITH", "EXPLAIN", "SHOW", "PRAGMA", "DESCRIBE", "DESC"}


def _handle_sql_query(args: dict) -> dict:
    cs = args.get("connection_string", "").strip()
    sql_text = args.get("sql", "").strip()
    params = list(args.get("params") or [])
    max_rows = min(int(args.get("max_rows") or 100), MAX_ROWS_HARD)

    if not cs:
        return _text("Error: connection_string is required.")
    if not sql_text:
        return _text("Error: sql is required.")

    first_token = sql_text.lstrip().split(maxsplit=1)[0].upper().rstrip(";")
    if first_token not in _READONLY_PREFIXES:
        return _text(
            f"Error: sql_query only permits read-only statements "
            f"(SELECT / WITH / EXPLAIN). "
            f"Use sql_execute for {first_token}."
        )

    try:
        driver, conn = _parse_conn(cs)
        try:
            cur = conn.cursor()
            cur.execute(sql_text, params) if params else cur.execute(sql_text)
            raw_rows = cur.fetchmany(max_rows)
            cols, rows = _rows_to_list(cur, raw_rows)
            output = {
                "columns": cols,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(rows) >= max_rows,
            }
            return _text(json.dumps(output, indent=2, default=str))
        finally:
            conn.close()
    except Exception as exc:
        return _text(f"Error: {exc}")


def _handle_sql_execute(args: dict) -> dict:
    cs = args.get("connection_string", "").strip()
    sql_text = args.get("sql", "").strip()
    params = list(args.get("params") or [])

    if not cs:
        return _text("Error: connection_string is required.")
    if not sql_text:
        return _text("Error: sql is required.")

    try:
        driver, conn = _parse_conn(cs)
        try:
            cur = conn.cursor()
            cur.execute(sql_text, params) if params else cur.execute(sql_text)
            affected = cur.rowcount if cur.rowcount is not None else -1
            conn.commit()
            return _text(
                json.dumps({"status": "ok", "affected_rows": affected}, indent=2)
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()
    except Exception as exc:
        return _text(f"Error: {exc}")


def _handle_sql_list_tables(args: dict) -> dict:
    cs = args.get("connection_string", "").strip()
    if not cs:
        return _text("Error: connection_string is required.")
    try:
        driver, conn = _parse_conn(cs)
        try:
            tables = _list_tables_impl(driver, conn)
            return _text(
                json.dumps({"tables": tables, "count": len(tables)}, indent=2)
            )
        finally:
            conn.close()
    except Exception as exc:
        return _text(f"Error: {exc}")


def _handle_sql_describe_table(args: dict) -> dict:
    cs = args.get("connection_string", "").strip()
    table_name = args.get("table_name", "").strip()
    if not cs:
        return _text("Error: connection_string is required.")
    if not table_name:
        return _text("Error: table_name is required.")
    try:
        driver, conn = _parse_conn(cs)
        try:
            cols = _describe_table_impl(driver, conn, table_name)
            return _text(
                json.dumps(
                    {"table": table_name, "columns": cols, "column_count": len(cols)},
                    indent=2,
                )
            )
        finally:
            conn.close()
    except Exception as exc:
        return _text(f"Error: {exc}")


_TOOL_HANDLERS = {
    "sql_query": _handle_sql_query,
    "sql_execute": _handle_sql_execute,
    "sql_list_tables": _handle_sql_list_tables,
    "sql_describe_table": _handle_sql_describe_table,
}


# ── Main MCP dispatch ──────────────────────────────────────────────────────────

def _handle(request: dict):
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sql-mcp-server", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return _err(req_id, -32601, f"Unknown tool: {name}")
        try:
            result = handler(args)
        except Exception as exc:
            result = _text(f"Unexpected server error: {exc}")
        return _ok(req_id, result)

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
