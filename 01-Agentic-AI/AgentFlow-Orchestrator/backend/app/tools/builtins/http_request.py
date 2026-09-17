"""HttpRequest tool — makes HTTP GET/POST/PUT/DELETE requests.

Permission level: EXTERNAL_ACTION
"""

from typing import Any

from app.models.tool_schema import ToolSpec
from app.tools.registry import Tool


class HttpRequest(Tool):
    """Make an HTTP request to a URL."""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                id="http_request",
                name="HTTP Request",
                description="Make an HTTP request. Parameters: url (str, required), method (str, default 'GET'), headers (dict, optional), body (str, optional), timeout_seconds (int, default 30).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to request"},
                        "method": {"type": "string", "default": "GET", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                        "headers": {"type": "object", "description": "HTTP headers"},
                        "body": {"type": "string", "description": "Request body (for POST/PUT/PATCH)"},
                        "timeout_seconds": {"type": "integer", "default": 30},
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "status_code": {"type": "integer"},
                        "headers": {"type": "object"},
                        "body": {"type": "string"},
                    },
                },
                permission_level="EXTERNAL_ACTION",
            )
        )

    async def execute(self, **params: Any) -> dict:
        url = params.get("url")
        if not url:
            return {"success": False, "output": None, "error": "Missing required parameter: url"}

        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        body = params.get("body")
        timeout = params.get("timeout_seconds", 30)

        try:
            import httpx

            async with httpx.AsyncClient(timeout=timeout) as client:
                request_kwargs: dict[str, Any] = {"headers": headers}
                if body and method in ("POST", "PUT", "PATCH"):
                    request_kwargs["content"] = body

                response = await client.request(method, url, **request_kwargs)

                return {
                    "success": 200 <= response.status_code < 400,
                    "output": {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": response.text,
                    },
                    "error": None if response.status_code < 400 else f"HTTP {response.status_code}",
                }
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}