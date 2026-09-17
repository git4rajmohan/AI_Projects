"""Tests for the tools and agents API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class TestToolsAPI:
    """Test the /api/tools endpoints."""

    @pytest.mark.asyncio
    async def test_list_tools(self):
        """GET /api/tools returns all built-in tools."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/tools")

        assert response.status_code == 200
        tools = response.json()
        tool_ids = [t["id"] for t in tools]
        assert "file_reader" in tool_ids
        assert "file_writer" in tool_ids
        assert "python_executor" in tool_ids
        assert "calculator" in tool_ids
        assert "http_request" in tool_ids
        assert "web_search" in tool_ids

    @pytest.mark.asyncio
    async def test_get_tool(self):
        """GET /api/tools/{id} returns tool details."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/tools/calculator")

        assert response.status_code == 200
        tool = response.json()
        assert tool["id"] == "calculator"
        assert tool["name"] == "Calculator"
        assert tool["permission_level"] == "READ"

    @pytest.mark.asyncio
    async def test_get_tool_not_found(self):
        """GET /api/tools/{id} returns 404 for unknown tool."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/tools/nonexistent")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_calculator(self):
        """POST /api/tools/{id}/execute runs the calculator."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/tools/calculator/execute",
                json={"params": {"expression": "6 * 7"}},
            )

        assert response.status_code == 200
        result = response.json()
        assert result["success"]
        assert result["output"]["result"] == 42


class TestAgentsAPI:
    """Test the /api/agents endpoints."""

    @pytest.mark.asyncio
    async def test_list_agents(self):
        """GET /api/agents returns agents from stored plans (may be empty)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/agents")

        assert response.status_code == 200
        # May be empty if no plans exist, but should be a list
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_execute_agent_no_spec(self):
        """POST /api/agents/execute returns 422 if no agent_spec provided."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agents/execute",
                json={"intent": "test"},
            )

        assert response.status_code == 422