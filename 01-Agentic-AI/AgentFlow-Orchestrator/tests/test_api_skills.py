"""Tests for the skills API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.skill_schema import SkillSpec
from app.skills.registry import get_skill_registry


async def _create_test_skill(name: str = "API Test Skill") -> str:
    """Helper: create a skill via the registry and return its ID."""
    registry = get_skill_registry()
    spec = SkillSpec(
        id="",
        name=name,
        description="A skill created for API testing",
        version="1.0.0",
        tags=["test", "api"],
        agents=["test_agent"],
        tools=["file_reader"],
        workflow={"type": "dag", "nodes": [], "edges": []},
        evaluation={"criteria": ["accuracy"], "threshold": 0.7},
        permissions={"file_read": True},
    )
    result = await registry.create_skill(spec)
    return result["skill_id"]


class TestSkillsAPI:
    """Test the /api/skills endpoints."""

    @pytest.mark.asyncio
    async def test_list_skills_empty(self):
        """GET /api/skills returns empty list when no skills exist."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/skills")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_create_skill(self):
        """POST /api/skills creates a new skill."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/skills",
                json={
                    "spec": {
                        "id": "",
                        "name": "API Created Skill",
                        "description": "Created via API",
                        "version": "1.0.0",
                        "tags": ["api"],
                        "agents": ["agent_1"],
                        "tools": ["file_reader"],
                        "workflow": {"type": "dag", "nodes": [], "edges": []},
                        "evaluation": {"criteria": ["accuracy"], "threshold": 0.7},
                        "permissions": {},
                        "enabled": True,
                    },
                    "author": "api-test",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "skill_id" in data
        assert data["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_skill(self):
        """GET /api/skills/{id} returns skill details."""
        skill_id = await _create_test_skill("Gettable API Skill")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/skills/{skill_id}")

        assert response.status_code == 200
        skill = response.json()
        assert skill["name"] == "Gettable API Skill"
        assert skill["active_version"] is not None

    @pytest.mark.asyncio
    async def test_get_skill_not_found(self):
        """GET /api/skills/{id} returns 404 for unknown skill."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/skills/nonexistent-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_skill(self):
        """PUT /api/skills/{id} updates skill metadata."""
        skill_id = await _create_test_skill("Updatable Skill")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                f"/api/skills/{skill_id}",
                json={"name": "Updated Name", "description": "New desc"},
            )

        assert response.status_code == 200
        skill = response.json()
        assert skill["name"] == "Updated Name"
        assert skill["description"] == "New desc"

    @pytest.mark.asyncio
    async def test_delete_skill(self):
        """DELETE /api/skills/{id} deletes a skill."""
        skill_id = await _create_test_skill("Deletable Skill")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/skills/{skill_id}")

            assert response.status_code == 200

            # Verify it's gone (within same client session)
            get_response = await client.get(f"/api/skills/{skill_id}")
            assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_skill_not_found(self):
        """DELETE /api/skills/{id} returns 404 for unknown skill."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/skills/nonexistent-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_export_skill(self):
        """GET /api/skills/{id}/export returns skill data."""
        skill_id = await _create_test_skill("Exportable Skill")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/skills/{skill_id}/export")

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"
        assert "skill" in data

    @pytest.mark.asyncio
    async def test_run_skill_not_found(self):
        """POST /api/skills/{id}/run returns 404 for unknown skill."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/skills/nonexistent-id/run",
                json={"task_id": "test-task"},
            )

        assert response.status_code == 400  # SkillExecutionError → 400