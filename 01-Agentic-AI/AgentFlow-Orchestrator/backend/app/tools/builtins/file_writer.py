"""FileWriter tool — writes content to disk.

Permission level: WRITE
"""

from typing import Any

from app.models.tool_schema import ToolSpec
from app.tools.registry import Tool


class FileWriter(Tool):
    """Write content to a file on the local filesystem."""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                id="file_writer",
                name="File Writer",
                description="Write content to a file on disk. Parameters: path (str, required), content (str, required), encoding (str, default 'utf-8'), append (bool, default False).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute or relative file path"},
                        "content": {"type": "string", "description": "Content to write"},
                        "encoding": {"type": "string", "default": "utf-8"},
                        "append": {"type": "boolean", "default": False},
                    },
                    "required": ["path", "content"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "bytes_written": {"type": "integer"},
                        "path": {"type": "string"},
                    },
                },
                permission_level="WRITE",
            )
        )

    async def execute(self, **params: Any) -> dict:
        path = params.get("path")
        content = params.get("content")
        if not path or content is None:
            return {"success": False, "output": None, "error": "Missing required parameters: path, content"}

        encoding = params.get("encoding", "utf-8")
        append = params.get("append", False)

        try:
            import os

            # Create parent directories if needed
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

            mode = "a" if append else "w"
            with open(path, mode, encoding=encoding) as f:
                f.write(content)

            bytes_written = len(content.encode(encoding))

            return {
                "success": True,
                "output": {
                    "bytes_written": bytes_written,
                    "path": os.path.abspath(path),
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}