#!/usr/bin/env python3
"""AgilePoint Live API MCP Server.

Connects to a running AgilePoint NX instance and exposes four workflow tools:

  get_worklist_by_user(user_name, status)
      Retrieves manual work items (tasks) for a given user and status.

  query_worklist_sql(sql_where_clause)
      Queries work items using a SQL WHERE clause (without the WHERE keyword).

  query_proc_instances(column_name, operator, where_clause, is_value)
      Queries process instances using a structured query expression.

  query_proc_instances_sql(sql_where_clause)
      Queries process instances using a SQL WHERE clause (without the WHERE keyword).

Configuration (set via mcp_servers.yaml ``stdio.env``):
  AGILEPOINT_DOMAIN      server base URL, e.g. https://eformqa.agilityclouds.com
  AGILEPOINT_USER        username (no domain prefix), e.g. rajmohan
  AGILEPOINT_PASSWORD    password
  AGILEPOINT_SERVICE     'AgilePointServer' (OnPremises default)
  AGILEPOINT_API_PORT    API port for cloud instances, e.g. 13490 (default: '' = same host)

Authentication:
  OnPremises instances use HTTP Basic auth (Authorization: Basic ...).
  Cloud/OnDemand instances (agilityclouds.com) use OIDC Authorization Code flow:
    1. GET /idp/auth               → IDP session cookies
    2. GET /idp/login              → HTML form with CSRF token + AD domain
    3. POST /idp/login/activedirectory  → AD credential submission
    4. Follow redirects            → authorization code at /login/callback
    5. GET /login/callback?code=   → portal exchanges code, sets AP_Auth cookie
    6. Decode AP_Auth cookie       → Bearer token for port-13490 API calls
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.parse
from typing import Any

import httpx

# ── Configuration (read once at startup) ──────────────────────────────────────

_BASE_URL: str = os.environ.get("AGILEPOINT_DOMAIN", "").rstrip("/")
_USER: str = os.environ.get("AGILEPOINT_USER", "")
_PASSWORD: str = os.environ.get("AGILEPOINT_PASSWORD", "")
_SERVICE: str = os.environ.get("AGILEPOINT_SERVICE", "AgilePointServer")
# For cloud: API lives on a separate port (e.g. 13490); blank = same as _BASE_URL
_API_PORT: str = os.environ.get("AGILEPOINT_API_PORT", "")

# Cloud instances use IDP OIDC flow; OnPremises uses Basic auth.
_USE_IDP: bool = "agilityclouds.com" in _BASE_URL.lower() or bool(_API_PORT)

# Derive the API base URL (may include a different port for cloud)
if _API_PORT:
    # e.g. https://eformqa.agilityclouds.com:13490
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(_BASE_URL)
    _API_BASE: str = f"{_parsed.scheme}://{_parsed.hostname}:{_API_PORT}"
else:
    _API_BASE: str = _BASE_URL

# OIDC constants (cloud only)
_IDP_CLIENT_ID = "portalv2"
_IDP_REDIRECT_URI = f"{_BASE_URL}/login/callback"
_IDP_SCOPE = "openid profile email offline_access claims.advanced"
_IDP_RESOURCE = f"{_API_BASE}/{_SERVICE}"

# ── Bearer token cache (cloud only) ──────────────────────────────────────────

_bearer_token: str = ""
_token_expiry: float = 0.0   # Unix timestamp when token expires
_TOKEN_REFRESH_MARGIN: int = 120  # refresh 2 min before actual expiry


def _parse_jwt_expiry(token: str) -> float:
    """Extract 'exp' claim from a JWT without verifying the signature."""
    try:
        # JWT is header.payload.signature (all base64url)
        # The token may be prefixed with 'ApIdp:' — strip it
        jwt_part = token.split(":", 1)[-1] if ":" in token else token
        payload_b64 = jwt_part.split(".")[1]
        # base64url decode (pad to multiple of 4)
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload.get("exp", 0))
    except Exception:  # noqa: BLE001
        return 0.0


def _get_bearer_token() -> tuple[str, str | None]:
    """Return a valid Bearer token for cloud API calls.

    Runs the full OIDC Authorization Code flow via the Active Directory login
    form if no cached token is available or the cached token is about to expire.
    Returns (token_string, error_or_None).
    The token_string should be used verbatim in the Authorization header:
        Authorization: Bearer ApIdp:<JWT>
    """
    global _bearer_token, _token_expiry  # noqa: PLW0603

    if _bearer_token and time.time() < _token_expiry - _TOKEN_REFRESH_MARGIN:
        return _bearer_token, None

    if not _BASE_URL:
        return "", "AGILEPOINT_DOMAIN is not configured"
    if not _USER or not _PASSWORD:
        return "", "AGILEPOINT_USER or AGILEPOINT_PASSWORD is not configured"

    # Use a short-lived client without follow_redirects so we control each hop
    C = httpx.Client(verify=False, timeout=90, follow_redirects=False)  # noqa: S501
    try:
        # ── 1. Start OIDC — set IDP interaction cookies ───────────────────────
        r1 = C.get(f"{_BASE_URL}/idp/auth", params={
            "client_id": _IDP_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": _IDP_REDIRECT_URI,
            "scope": _IDP_SCOPE,
            "resource": _IDP_RESOURCE,
        })
        if r1.status_code not in (302, 303):
            return "", f"OIDC auth start failed (HTTP {r1.status_code})"

        # ── 2. GET login page — extract CSRF token and AD domain ──────────────
        r2 = C.get(f"{_BASE_URL}/idp/login")
        if r2.status_code != 200:
            return "", f"GET /idp/login failed (HTTP {r2.status_code})"

        csrf_m = re.search(
            r'value=([^\s>]+)[^>]*name=__RequestVerificationToken'
            r'|name=__RequestVerificationToken[^>]*value=([^\s>]+)',
            r2.text,
        )
        csrf_token = next(g for g in csrf_m.groups() if g) if csrf_m else ""
        if not csrf_token:
            return "", "CSRF token not found in /idp/login form"

        dom_m = re.search(r'name=domain[^>]*value=([^\s>]+)', r2.text)
        ad_domain = dom_m.group(1) if dom_m else ""

        # ── 3. POST AD credentials ────────────────────────────────────────────
        r3 = C.post(
            f"{_BASE_URL}/idp/login/activedirectory",
            data={
                "domain": ad_domain,
                "userName": _USER,
                "password": _PASSWORD,
                "__RequestVerificationToken": csrf_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{_BASE_URL}/idp/login",
            },
        )
        if r3.status_code not in (301, 302, 303):
            return "", (
                f"AD login failed (HTTP {r3.status_code}). "
                "Check AGILEPOINT_USER and AGILEPOINT_PASSWORD."
            )

        # ── 4. Follow redirects until we see the auth code ────────────────────
        current = r3
        auth_code: str = ""
        for _ in range(10):
            loc = current.headers.get("location", "")
            if not loc:
                break
            if "code=" in loc:
                m = re.search(r'[?&]code=([^&\s]+)', loc)
                if m:
                    auth_code = m.group(1)
                    break
            url = f"{_BASE_URL}{loc}" if loc.startswith("/") else loc
            current = C.get(url)

        if not auth_code:
            return "", "Authorization code not found in OIDC redirect chain"

        # ── 5. Hit /login/callback — portal does server-side token exchange
        #       and sets AP_Auth cookie with the Bearer token ─────────────────
        r5 = C.get(
            f"{_BASE_URL}/login/callback",
            params={"code": urllib.parse.unquote(auth_code)},
        )
        if r5.status_code not in (200, 302, 303):
            return "", f"/login/callback failed (HTTP {r5.status_code})"

        # ── 6. Decode AP_Auth cookie ──────────────────────────────────────────
        ap_auth_raw = C.cookies.get("AP_Auth", "")
        if not ap_auth_raw:
            return "", "AP_Auth cookie not set after /login/callback — login may have failed"

        try:
            ap_auth = json.loads(urllib.parse.unquote(ap_auth_raw))
            auth_value: str = ap_auth.get("auth", "")
        except Exception as exc:  # noqa: BLE001
            return "", f"Failed to decode AP_Auth cookie: {exc}"

        if not auth_value.startswith("Bearer "):
            return "", f"Unexpected AP_Auth format: {auth_value[:60]}"

        # auth_value is e.g. 'Bearer ApIdp:eyJ...' — use it verbatim
        # Extract just the token part (everything after 'Bearer ')
        token_part = auth_value[len("Bearer "):]
        expiry = _parse_jwt_expiry(token_part)

        _bearer_token = auth_value
        _token_expiry = expiry if expiry > 0 else time.time() + 7200
        return _bearer_token, None

    except httpx.HTTPError as exc:
        return "", f"HTTP error during OIDC login: {exc}"
    finally:
        C.close()


# ── Shared HTTP helper ────────────────────────────────────────────────────────

def _post(path: str, body: dict) -> dict:
    """POST *body* to the AgilePoint Workflow API path.

    Returns a dict with either a ``result`` key (list or dict from the API)
    or an ``error`` key with a human-readable message.
    Retries once on auth failure (401/403) by forcing token refresh.
    """
    global _bearer_token  # noqa: PLW0603

    url = f"{_API_BASE}/{_SERVICE}/Workflow/{path}"

    for attempt in range(2):
        if _USE_IDP:
            token, err = _get_bearer_token()
            if err:
                return {"error": err}
            auth_headers = {
                "Authorization": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            cred = base64.b64encode(f"{_USER}:{_PASSWORD}".encode()).decode("ascii")
            auth_headers = {
                "Authorization": f"Basic {cred}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

        try:
            with httpx.Client(verify=False, timeout=90, follow_redirects=False) as C:  # noqa: S501
                resp = C.post(url, json=body, headers=auth_headers)
        except httpx.TimeoutException:
            return {"error": f"Request timed out: {url}"}
        except httpx.HTTPError as exc:
            return {"error": f"HTTP error calling {url}: {exc}"}

        if resp.status_code in (401, 403):
            if attempt == 0:
                # Force token refresh on retry
                _bearer_token = ""
                continue
            return {"error": f"Authentication failed (HTTP {resp.status_code}). Check credentials."}

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "error": (
                    f"HTTP {exc.response.status_code} from AgilePoint: "
                    f"{exc.response.text[:400]}"
                )
            }

        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type:
            return {
                "error": (
                    f"Non-JSON response (HTTP {resp.status_code}, "
                    f"Content-Type: {content_type}). "
                    f"Body snippet: {resp.text[:300]}"
                )
            }

        try:
            return {"result": resp.json()}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to parse JSON response: {exc}. Body: {resp.text[:200]}"}

    return {"error": "Authentication failed after retry"}


# ── Tool implementations ──────────────────────────────────────────────────────

def _add_task_urls(items: list) -> list:
    """Inject a task_url field into each work item using its WorkItemID."""
    base = _BASE_URL
    for item in items:
        wid = item.get("WorkItemID", "")
        if wid:
            item["task_url"] = (
                f"{base}/ApplicationBuilder/eFormRender.html?WID={wid}"
            )
    return items


def get_worklist_by_user(args: dict) -> str:
    """Retrieve manual work items for a user filtered by status.

    AgilePoint API: POST /AgilePointServer/Workflow/GetWorkListByUserID
    """
    user_name = args.get("user_name", "").strip()
    status = args.get("status", "").strip()

    if not user_name:
        return "Error: user_name is required"

    body: dict = {"UserName": user_name}
    if status:
        body["Status"] = status

    outcome = _post("GetWorkListByUserID", body)
    if "error" in outcome:
        return f"Error: {outcome['error']}"

    items = outcome["result"]
    if not items:
        return f"No work items found for user '{user_name}'" + (
            f" with status '{status}'" if status else ""
        )
    return json.dumps(_add_task_urls(items), indent=2)


def _apply_simple_filter(items: list, sql_where: str) -> list:
    """Apply simple Field='Value' equality and Field LIKE '%val%' filters client-side.

    The AgilePoint QueryWorkListUsingSQL endpoint ignores the WHERE clause and
    always returns all items, so we filter the result in Python.
    Supports: single or chained equality/LIKE conditions joined by AND.
    LIKE supports % (any chars) and _ (any single char) wildcards.
    Unrecognised syntax is silently skipped and the full list is returned.

    Handles both SQL column names (USER_ID, STATUS, APPL_NAME) and JSON field
    names (UserID, Status, ApplName) — maps them before matching.
    """
    import re as _re
    # SQL column name → JSON field name mapping (uppercase_underscored → camelCase)
    _COL_MAP: dict[str, str] = {
        "user_id":          "UserID",
        "original_user_id": "OriginalUserID",
        "status":           "Status",
        "appl_name":        "ApplName",
        "def_name":         "DefName",
        "proc_inst_id":     "ProcInstID",
        "work_item_id":     "WorkItemID",
        "display_name":     "DisplayName",
        "priority":         "Priority",
        "proc_initiator":   "ProcInitiator",
    }

    # Parse LIKE patterns first (before equality, to avoid mis-matching)
    like_pattern = _re.compile(
        r"(\w+)\s+LIKE\s+['\"]([^'\"]+)['\"]",
        _re.IGNORECASE,
    )
    # Parse equality patterns: FieldName = 'value'
    eq_pattern = _re.compile(
        r"(\w+)\s*=\s*['\"]([^'\"]+)['\"]",
        _re.IGNORECASE,
    )

    like_conditions = like_pattern.findall(sql_where)
    # Remove LIKE clauses before parsing equality so they don't double-match
    sql_for_eq = like_pattern.sub("", sql_where)
    eq_conditions = eq_pattern.findall(sql_for_eq)

    if not eq_conditions and not like_conditions:
        return items

    filtered = items

    for col, value in eq_conditions:
        field = _COL_MAP.get(col.lower(), col)
        filtered = [
            item for item in filtered
            if str(item.get(field, "")).lower() == value.lower()
        ]

    for col, like_val in like_conditions:
        field = _COL_MAP.get(col.lower(), col)
        # Convert SQL LIKE pattern (% = any chars, _ = one char) to regex
        parts = like_val.split("%")
        regex_str = ".*".join(_re.escape(p).replace(r"\_", ".") for p in parts)
        compiled = _re.compile(f"^{regex_str}$", _re.IGNORECASE)
        filtered = [
            item for item in filtered
            if compiled.match(str(item.get(field, "")))
        ]

    return filtered


def get_worklist_summary(args: dict) -> str:
    """Return a breakdown of work item counts by Status and ApplName for the current user."""
    outcome = _post("QueryWorkListUsingSQL", {"sqlWhereClause": "1=1"})
    if "error" in outcome:
        return f"Error: {outcome['error']}"
    items = outcome["result"]
    if not isinstance(items, list):
        return "No work items found"
    from collections import Counter
    status_counts = dict(Counter(x.get("Status", "Unknown") for x in items))
    app_counts = dict(Counter(x.get("ApplName", "Unknown") for x in items))
    result = {
        "total": len(items),
        "by_status": dict(sorted(status_counts.items(), key=lambda kv: -kv[1])),
        "by_app": dict(sorted(app_counts.items(), key=lambda kv: -kv[1])),
    }
    return json.dumps(result, indent=2)


def query_worklist_sql(args: dict) -> str:
    """Query work items using a SQL WHERE clause.

    AgilePoint API: POST /AgilePointServer/Workflow/QueryWorkListUsingSQL
    Note: pass only the WHERE clause content, without the WHERE keyword.

    The cloud API returns all items regardless of the WHERE clause, so
    simple Field='Value' conditions are applied client-side after fetching.
    """
    sql_where = args.get("sql_where_clause", "").strip()
    if not sql_where:
        return "Error: sql_where_clause is required"

    # The cloud API rejects any real WHERE clause with HTTP 400 — always fetch
    # all items with 1=1, then filter client-side via _apply_simple_filter.
    outcome = _post("QueryWorkListUsingSQL", {"sqlWhereClause": "1=1"})
    if "error" in outcome:
        return f"Error: {outcome['error']}"

    items = outcome["result"]
    if not isinstance(items, list):
        return "No work items matched the WHERE clause"

    # Apply client-side filtering (server ignores WHERE on this endpoint)
    filtered = _apply_simple_filter(items, sql_where)

    if not filtered:
        return f"No work items matched: {sql_where} (searched {len(items)} total items)"

    from collections import Counter as _Counter
    max_items = 10
    shown = _add_task_urls(filtered[:max_items])
    result = {
        "matched_count": len(filtered),
        "total_scanned": len(items),
        "by_app": dict(sorted(
            _Counter(x.get("ApplName", "Unknown") for x in filtered).items(),
            key=lambda kv: -kv[1],
        )),
        "by_status": dict(sorted(
            _Counter(x.get("Status", "Unknown") for x in filtered).items(),
            key=lambda kv: -kv[1],
        )),
        "showing": len(shown),
        "items": shown,
    }
    return json.dumps(result, indent=2)


def query_proc_instances(args: dict) -> str:
    """Query process instances using a structured expression.

    AgilePoint API: POST /AgilePointServer/Workflow/QueryProcInsts
    Builds a WFQueryExpr from the supplied column_name, operator, where_clause,
    and is_value flag.
    """
    column_name = args.get("column_name", "").strip()
    operator = args.get("operator", "").strip()
    where_clause = args.get("where_clause", "").strip()

    if not column_name or not operator or not where_clause:
        return "Error: column_name, operator, and where_clause are all required"

    is_value: bool = bool(args.get("is_value", True))
    body = {
        "ColumnName": column_name,
        "Operator": operator,
        "WhereClause": where_clause,
        "IsValue": is_value,
    }

    outcome = _post("QueryProcInsts", body)
    if "error" in outcome:
        return f"Error: {outcome['error']}"

    instances = outcome["result"]
    if not instances:
        return "No process instances matched the query expression"
    return json.dumps(instances, indent=2)


def query_proc_instances_sql(args: dict) -> str:
    """Query process instances using a SQL WHERE clause.

    AgilePoint API: POST /AgilePointServer/Workflow/QueryProcInstsUsingSQL
    Note: pass only the WHERE clause content, without the WHERE keyword.
    """
    sql_where = args.get("sql_where_clause", "").strip()
    if not sql_where:
        return "Error: sql_where_clause is required"

    outcome = _post("QueryProcInstsUsingSQL", {"sqlWhereClause": sql_where})
    if "error" in outcome:
        return f"Error: {outcome['error']}"

    instances = outcome["result"]
    if not instances:
        return "No process instances matched the WHERE clause"
    max_items = 10
    if isinstance(instances, list):
        shown = instances[:max_items]
        result = {
            "matched_count": len(instances),
            "showing": len(shown),
            "items": shown,
        }
    else:
        result = {"matched_count": 1, "showing": 1, "items": [instances]}
    return json.dumps(result, indent=2)


# ── Dispatch table ────────────────────────────────────────────────────────────

_DISPATCH = {
    "get_worklist_by_user": get_worklist_by_user,
    "get_worklist_summary": get_worklist_summary,
    "query_worklist_sql": query_worklist_sql,
    "query_proc_instances": query_proc_instances,
    "query_proc_instances_sql": query_proc_instances_sql,
}

# ── MCP tool definitions ──────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "get_worklist_by_user",
        "description": (
            "Retrieve AgilePoint manual work items (tasks) for a specified user. "
            "You can filter by task status. Multiple statuses can be passed as a "
            "semicolon-delimited list, e.g. 'New;Assigned'. "
            "Valid statuses: New, Assigned, Removed, Completed, Reassigned, "
            "Canceled, Overdue, Carbon."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_name": {
                    "type": "string",
                    "description": (
                        "Qualified Windows user name, e.g. 'MYDOMAIN\\\\brian.lucas' "
                        "or 'myhost\\\\john.smith'."
                    ),
                },
                "status": {
                    "type": "string",
                    "description": (
                        "Task status filter. Leave blank to get all statuses. "
                        "Multiple values separated by semicolons, e.g. 'New;Assigned'."
                    ),
                    "default": "",
                },
            },
            "required": ["user_name"],
        },
    },
    {
        "name": "get_worklist_summary",
        "description": (
            "Return a count of AgilePoint work items grouped by Status AND by ApplName "
            "for the current authenticated user. Use this to answer questions like "
            "'how many tasks do I have?', 'give me counts for all statuses', or "
            "'how many tasks for app X?' — the by_app field shows the EXACT app names "
            "and their task counts, so you can match what the user asked to the real name. "
            "Returns: {total, by_status: {New: N, ...}, by_app: {AppName: N, ...}}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "query_worklist_sql",
        "description": (
            "Query AgilePoint manual work items by status or app name. "
            "Pass only the WHERE clause content — do NOT include the WHERE keyword. "
            "Filter by exact match (e.g. \"Status='New'\") or by partial app name "
            "using LIKE with % wildcards (e.g. \"ApplName LIKE '%PeoplePicker%'\"). "
            "When the exact app name is unknown, always use LIKE with % on both sides "
            "so partial names like 'people picker' still match. "
            "NOTE: Results include tasks for ALL users visible to this service account "
            "(e.g. both rajmohan and alice may appear). To filter to one user, add "
            "UserID = 'DOMAIN\\\\username' to the WHERE clause using the exact "
            "domain-qualified name, e.g. \"UserID = 'SERVER2022-BASE\\\\rajmohan'\". "
            "The result includes by_app and by_status breakdowns covering ALL matched "
            "items — always use those for counts, not the items list (which is capped at 10)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql_where_clause": {
                    "type": "string",
                    "description": (
                        "SQL WHERE clause without the WHERE keyword. "
                        "Valid fields: Status, ApplName, DisplayName, Priority. "
                        "Supports = for exact match and LIKE with % wildcards for partial match. "
                        "Examples: \"Status='New'\", \"ApplName LIKE '%PeoplePicker%'\", "
                        "\"Status='New' AND ApplName LIKE '%Purchase%'\""
                    ),
                },
            },
            "required": ["sql_where_clause"],
        },
    },
    {
        "name": "query_proc_instances",
        "description": (
            "Query AgilePoint process instances using a structured filter expression. "
            "Specify the column to filter on, the comparison operator, and the value. "
            "Common columns: PROC_INITIATOR, PROC_INST_ID, DEF_NAME, STATUS, APPL_NAME. "
            "Common operators: EQ, NEQ, GT, LT, GTE, LTE, LIKE."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "column_name": {
                    "type": "string",
                    "description": (
                        "Database column name to filter on, "
                        "e.g. 'PROC_INITIATOR', 'DEF_NAME', 'STATUS'."
                    ),
                },
                "operator": {
                    "type": "string",
                    "description": (
                        "Comparison operator, e.g. 'EQ' (equals), 'LIKE', 'NEQ'."
                    ),
                },
                "where_clause": {
                    "type": "string",
                    "description": (
                        "The value or column to compare against, "
                        "e.g. 'MYDOMAIN\\\\brian.lucas' or 'Completed'."
                    ),
                },
                "is_value": {
                    "type": "boolean",
                    "description": (
                        "True (default) if where_clause is a literal value; "
                        "False if it is a column reference."
                    ),
                    "default": True,
                },
            },
            "required": ["column_name", "operator", "where_clause"],
        },
    },
    {
        "name": "query_proc_instances_sql",
        "description": (
            "Query AgilePoint process instances using a SQL WHERE clause. "
            "Pass only the WHERE clause content — do NOT include the WHERE keyword. "
            "Example: \"PROC_INST_ID='0FD3088F40B640D4AFE41AEEBDAE914B'\" or "
            "\"STATUS='Running' AND APPL_NAME='MyApp'\""
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql_where_clause": {
                    "type": "string",
                    "description": (
                        "SQL WHERE clause without the WHERE keyword. "
                        "References columns in the process instances table."
                    ),
                },
            },
            "required": ["sql_where_clause"],
        },
    },
]


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text_content(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


# ── MCP request handler ───────────────────────────────────────────────────────

def _handle(request: dict) -> dict | None:
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "agilepoint-api",
                "version": "1.0.0",
                "description": "AgilePoint NX live API — worklist and process instance queries",
            },
        })

    if method == "notifications/initialized":
        return None  # fire-and-forget notification

    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = _DISPATCH.get(tool_name)
        if handler is None:
            return _err(req_id, -32601, f"Tool not found: {tool_name}")

        try:
            text = handler(arguments)
        except Exception as exc:  # noqa: BLE001
            text = f"Tool error: {exc}"

        return _ok(req_id, _text_content(text))

    return _err(req_id, -32601, f"Method not found: {method}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            resp = _err(None, -32700, f"Parse error: {exc}")
            print(json.dumps(resp), flush=True)
            continue

        response = _handle(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
