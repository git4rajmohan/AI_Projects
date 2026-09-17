"""PythonExecutor tool — runs Python code in a restricted subprocess.

Permission level: WRITE (can execute arbitrary code)

Safety: runs in a subprocess with a timeout. Does NOT sandbox by default
(Phase 9 can add container-based isolation). For MVP, this is acceptable
since the Policy Engine gates execution.

Network egress is blocked at the source level (see _NETWORK_IMPORT_RE): without
this, an agent whose plan lists only python_executor (WRITE) — not web_search
or http_request (EXTERNAL_ACTION) — could reach the network via `requests`/
`urllib`/`socket` etc. and silently bypass the human-approval gate that
EXTERNAL_ACTION tools require.
"""

import re
import subprocess
import sys
import tempfile
from typing import Any

from app.models.tool_schema import ToolSpec
from app.tools.registry import Tool

# Output printed by executed code flows directly into the LLM's conversation history —
# cap it so a runaway print (e.g. a full dataframe dump) can't blow the context window.
MAX_OUTPUT_CHARS = 20_000

# Blocks common networking modules so python_executor can't be used to reach the
# network without going through the properly-gated web_search/http_request tools.
_NETWORK_MODULES = (
    "requests", "urllib", "urllib2", "urllib3", "http.client", "httplib",
    "socket", "httpx", "aiohttp", "ftplib", "smtplib", "telnetlib", "xmlrpc",
)
_NETWORK_IMPORT_RE = re.compile(
    r"^\s*(import\s+(" + "|".join(re.escape(m) for m in _NETWORK_MODULES) + r")\b"
    r"|from\s+(" + "|".join(re.escape(m) for m in _NETWORK_MODULES) + r")\b)",
    re.MULTILINE,
)


def _cap(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n...[truncated, {len(text) - MAX_OUTPUT_CHARS} more chars]"


class PythonExecutor(Tool):
    """Execute Python code and return stdout, stderr, and exit code."""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                id="python_executor",
                name="Python Executor",
                description="Execute Python code and return stdout, stderr, and exit code. Parameters: code (str, required), timeout_seconds (int, default 30).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"},
                        "timeout_seconds": {"type": "integer", "default": 30},
                    },
                    "required": ["code"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "stdout": {"type": "string"},
                        "stderr": {"type": "string"},
                        "exit_code": {"type": "integer"},
                        "timed_out": {"type": "boolean"},
                    },
                },
                permission_level="WRITE",
            )
        )

    async def execute(self, **params: Any) -> dict:
        code = params.get("code")
        if not code:
            return {"success": False, "output": None, "error": "Missing required parameter: code"}

        if _NETWORK_IMPORT_RE.search(code):
            return {
                "success": False,
                "output": None,
                "error": (
                    "python_executor cannot make network calls. Use the 'web_search' or "
                    "'http_request' tool instead — those require human approval, unlike code execution."
                ),
            }

        timeout = params.get("timeout_seconds", 30)

        try:
            # Write code to a temp file and execute
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(code)
                temp_path = f.name

            try:
                # Force UTF-8 on both ends — Windows' default locale encoding (cp1252/cp936)
                # otherwise mangles non-ASCII characters (em dashes, currency symbols, etc.)
                # that the LLM commonly writes into generated code/reports.
                import os

                child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
                result = subprocess.run(
                    [sys.executable, temp_path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    env=child_env,
                )
                return {
                    "success": result.returncode == 0,
                    "output": {
                        "stdout": _cap(result.stdout),
                        "stderr": _cap(result.stderr),
                        "exit_code": result.returncode,
                        "timed_out": False,
                    },
                    "error": None if result.returncode == 0 else result.stderr.strip()[:2000] or f"Exit code {result.returncode}",
                }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "output": {
                        "stdout": "",
                        "stderr": f"Execution timed out after {timeout}s",
                        "exit_code": -1,
                        "timed_out": True,
                    },
                    "error": f"Execution timed out after {timeout}s",
                }
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}
        finally:
            import os

            try:
                os.unlink(temp_path)
            except Exception:
                pass