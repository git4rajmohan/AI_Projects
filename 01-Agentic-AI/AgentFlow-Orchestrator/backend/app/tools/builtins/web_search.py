"""WebSearch tool — performs web searches.

Permission level: EXTERNAL_ACTION

MVP: Uses a simple HTTP-based search. Can be swapped for a real search API
(Serper, Brave, Google Custom Search) by setting the api_key in config.
Without an API key, returns a placeholder indicating configuration is needed.
"""

import os
from typing import Any

from app.models.tool_schema import ToolSpec
from app.tools.registry import Tool


class WebSearch(Tool):
    """Search the web for information."""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                id="web_search",
                name="Web Search",
                description="Search the web for information. Parameters: query (str, required), max_results (int, default 5).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "url": {"type": "string"},
                                    "snippet": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                permission_level="EXTERNAL_ACTION",
            )
        )

    async def execute(self, **params: Any) -> dict:
        query = params.get("query")
        if not query:
            return {"success": False, "output": None, "error": "Missing required parameter: query"}

        max_results = params.get("max_results", 5)

        # Check for a search API key (Serper, SerpApi, Brave, etc.)
        serper_key = os.environ.get("SERPER_API_KEY")
        serpapi_key = os.environ.get("SERPAPI_API_KEY")
        brave_key = os.environ.get("BRAVE_SEARCH_API_KEY")

        if serper_key:
            return await self._search_serper(query, max_results, serper_key)
        elif serpapi_key:
            return await self._search_serpapi(query, max_results, serpapi_key)
        elif brave_key:
            return await self._search_brave(query, max_results, brave_key)
        else:
            # No API key configured — return a placeholder
            return {
                "success": True,
                "output": {
                    "results": [],
                    "note": "Web search requires SERPER_API_KEY, SERPAPI_API_KEY, or BRAVE_SEARCH_API_KEY environment variable. Set one to enable real search.",
                    "query": query,
                },
                "error": None,
            }

    async def _search_serper(self, query: str, max_results: int, api_key: str) -> dict:
        """Search using Serper.dev API."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": max_results},
                )
                if response.status_code != 200:
                    return {"success": False, "output": None, "error": f"Serper API error: {response.status_code}"}

                data = response.json()
                results = []
                for item in data.get("organic", [])[:max_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                return {"success": True, "output": {"results": results}, "error": None}
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}

    async def _search_serpapi(self, query: str, max_results: int, api_key: str) -> dict:
        """Search using SerpApi (serpapi.com)."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://serpapi.com/search",
                    params={"q": query, "num": max_results, "api_key": api_key, "engine": "google"},
                )
                if response.status_code != 200:
                    return {"success": False, "output": None, "error": f"SerpApi error: {response.status_code}"}

                data = response.json()
                results = []
                for item in data.get("organic_results", [])[:max_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                return {"success": True, "output": {"results": results}, "error": None}
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}

    async def _search_brave(self, query: str, max_results: int, api_key: str) -> dict:
        """Search using Brave Search API."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    params={"q": query, "count": max_results},
                )
                if response.status_code != 200:
                    return {"success": False, "output": None, "error": f"Brave API error: {response.status_code}"}

                data = response.json()
                results = []
                for item in data.get("web", {}).get("results", [])[:max_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("description", ""),
                    })

                return {"success": True, "output": {"results": results}, "error": None}
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}