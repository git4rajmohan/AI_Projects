"""FileReader tool — reads file contents from disk.

Permission level: READ
"""

from typing import Any

from app.models.tool_schema import ToolSpec
from app.tools.registry import Tool


class FileReader(Tool):
    """Read a file from the local filesystem."""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                id="file_reader",
                name="File Reader",
                description=(
                    "Preview the contents of a small text/CSV file (capped at 20KB by default, "
                    "100KB max) so its structure and sample rows are visible. Do NOT use this to "
                    "bulk-process large files — use python_executor with pandas instead, since raw "
                    "file content is sent directly to the LLM and can exceed the context window. "
                    "Parameters: path (str, required), encoding (str, default 'utf-8'), "
                    "max_bytes (int, default 20000, hard-capped at 100000)."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute or relative file path"},
                        "encoding": {"type": "string", "default": "utf-8"},
                        "max_bytes": {"type": "integer", "default": 20_000},
                    },
                    "required": ["path"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "size_bytes": {"type": "integer"},
                        "truncated": {"type": "boolean"},
                    },
                },
                permission_level="READ",
            )
        )

    async def execute(self, **params: Any) -> dict:
        path = params.get("path")
        if not path:
            return {"success": False, "output": None, "error": "Missing required parameter: path"}

        encoding = params.get("encoding", "utf-8")
        # Hard cap regardless of what's requested — raw file content flows directly into the
        # LLM's conversation history and must never be large enough to blow the context window.
        max_bytes = min(params.get("max_bytes", 20_000), 100_000)

        try:
            import os

            if not os.path.exists(path):
                return {"success": False, "output": None, "error": f"File not found: {path}"}

            size = os.path.getsize(path)
            truncated = size > max_bytes

            with open(path, "r", encoding=encoding) as f:
                if truncated:
                    content = f.read(max_bytes)
                else:
                    content = f.read()

            return {
                "success": True,
                "output": {
                    "content": content,
                    "size_bytes": size,
                    "truncated": truncated,
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}