"""Tests for the memory and model routing API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.memory.manager import get_memory_manager


class TestMemoryAPI:
    """Test the /api/memory endpoints."""

    @pytest.mark.asyncio
    async def test_set_and_get_long_term(self):
        """POST then GET long-term memory."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Set
            response = await client.post(
                "/api/memory/long-term",
                json={"key": "api-test-key", "value": "api-test-value", "metadata": {}},
            )
            assert response.status_code == 200

            # Get
            response = await client.get("/api/memory/long-term/api-test-key")
            assert response.status_code == 200
            assert response.json()["value"] == "api-test-value"

    @pytest.mark.asyncio
    async def test_get_long_term_not_found(self):
        """GET non-existent key returns 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/memory/long-term/nonexistent-key-xyz")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_long_term(self):
        """GET long-term memory list."""
        manager = get_memory_manager()
        manager.set_long_term("api-list-key", "val")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/memory/long-term")

        assert response.status_code == 200
        assert "api-list-key" in response.json()["keys"]

    @pytest.mark.asyncio
    async def test_delete_long_term(self):
        """DELETE long-term memory key."""
        manager = get_memory_manager()
        manager.set_long_term("api-delete-key", "val")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/memory/long-term/api-delete-key")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_search_long_term(self):
        """GET search long-term memory."""
        manager = get_memory_manager()
        manager.set_long_term("api-search-key", "contains searchable text")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/memory/long-term/search?q=searchable")

        assert response.status_code == 200
        assert response.json()["count"] >= 1

    @pytest.mark.asyncio
    async def test_working_memory(self):
        """GET working memory for a task."""
        manager = get_memory_manager()
        manager.set_working("api-task-1", "key1", "val1")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/memory/working/api-task-1")

        assert response.status_code == 200
        assert response.json()["memory"]["key1"] == "val1"

    @pytest.mark.asyncio
    async def test_clear_working_memory(self):
        """DELETE working memory for a task."""
        manager = get_memory_manager()
        manager.set_working("api-task-2", "key1", "val1")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/memory/working/api-task-2")

        assert response.status_code == 200
        assert manager.get_all_working("api-task-2") == {}


class TestModelsAPI:
    """Test the /api/models endpoints."""

    @pytest.mark.asyncio
    async def test_list_tiers(self):
        """GET /api/models/tiers returns model tiers."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models/tiers")

        assert response.status_code == 200
        data = response.json()
        assert "tiers" in data
        assert len(data["tiers"]) == 3

    @pytest.mark.asyncio
    async def test_route_model(self):
        """POST /api/models/route returns routing info."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/models/route",
                json={
                    "intent": "Research AI tools and compare them",
                    "agent_model": "",
                    "agent_tools": ["web_search"],
                    "plan_agent_count": 3,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "tier" in data
        assert "model_name" in data
        assert "reasons" in data


class TestSkillRecommendationAPI:
    """Test the /api/skills/recommend endpoint."""

    @pytest.mark.asyncio
    async def test_recommend_endpoint(self):
        """GET /api/skills/recommend returns recommendations."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/skills/recommend",
                params={"intent": "Convert CSV to Excel", "max_results": 5},
            )

        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    @pytest.mark.asyncio
    async def test_recommend_no_match(self):
        """GET /api/skills/recommend with no matching skills returns empty."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/skills/recommend",
                params={"intent": "xyzzy qwerty nonmatching", "max_results": 5},
            )

        assert response.status_code == 200
        assert response.json()["count"] == 0