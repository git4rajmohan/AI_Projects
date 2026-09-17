"""Tests for the Skill Registry — CRUD operations and versioning.

Matches instruction.md section 25-27 (Skill Creation, Content, Versioning).
"""

import pytest

from app.models.skill_schema import SkillSpec
from app.skills.registry import SkillNotFoundError, SkillRegistry, get_skill_registry


def _make_skill_spec(
    name: str = "Test Skill",
    description: str = "A test skill",
    version: str = "1.0.0",
    tags: list[str] | None = None,
) -> SkillSpec:
    return SkillSpec(
        id="",
        name=name,
        description=description,
        version=version,
        tags=tags or ["test"],
        agents=["test_agent"],
        tools=["file_reader"],
        workflow={"type": "dag", "nodes": [], "edges": []},
        evaluation={"criteria": ["accuracy"], "threshold": 0.7},
        permissions={"file_read": True},
    )


class TestSkillRegistry:
    """Test SkillRegistry CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_skill(self):
        """Create a skill and verify it's stored."""
        registry = SkillRegistry()
        spec = _make_skill_spec(name="My Skill", description="Does things")

        result = await registry.create_skill(spec, author="tester")
        assert "skill_id" in result
        assert result["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_skill(self):
        """Get a skill by ID returns metadata + active version."""
        registry = SkillRegistry()
        spec = _make_skill_spec(name="Gettable Skill")
        result = await registry.create_skill(spec)

        skill = await registry.get_skill(result["skill_id"])
        assert skill is not None
        assert skill["name"] == "Gettable Skill"
        assert skill["active_version"] is not None
        assert skill["active_version"]["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_skill_not_found(self):
        """Getting a non-existent skill returns None."""
        registry = SkillRegistry()
        skill = await registry.get_skill("nonexistent-id")
        assert skill is None

    @pytest.mark.asyncio
    async def test_list_skills(self):
        """List skills returns all skills."""
        registry = SkillRegistry()
        await registry.create_skill(_make_skill_spec(name="Skill A"))
        await registry.create_skill(_make_skill_spec(name="Skill B"))

        skills = await registry.list_skills()
        names = [s["name"] for s in skills]
        assert "Skill A" in names
        assert "Skill B" in names

    @pytest.mark.asyncio
    async def test_update_skill(self):
        """Update skill metadata."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Original"))

        updated = await registry.update_skill(
            result["skill_id"],
            name="Updated Name",
            description="New description",
            tags=["new", "tags"],
        )
        assert updated is not None
        assert updated["name"] == "Updated Name"
        assert updated["description"] == "New description"
        assert "new" in updated["tags"]

    @pytest.mark.asyncio
    async def test_disable_skill(self):
        """Disable a skill via update."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Disable Me"))

        await registry.update_skill(result["skill_id"], enabled=False)

        # Should not appear in default list (enabled only)
        skills = await registry.list_skills(include_disabled=False)
        ids = [s["id"] for s in skills]
        assert result["skill_id"] not in ids

        # Should appear with include_disabled
        skills = await registry.list_skills(include_disabled=True)
        ids = [s["id"] for s in skills]
        assert result["skill_id"] in ids

    @pytest.mark.asyncio
    async def test_delete_skill(self):
        """Delete a skill and verify it's gone."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Delete Me"))

        deleted = await registry.delete_skill(result["skill_id"])
        assert deleted

        skill = await registry.get_skill(result["skill_id"])
        assert skill is None

    @pytest.mark.asyncio
    async def test_delete_skill_not_found(self):
        """Deleting a non-existent skill returns False."""
        registry = SkillRegistry()
        deleted = await registry.delete_skill("nonexistent")
        assert not deleted


class TestSkillVersioning:
    """Test skill version management."""

    @pytest.mark.asyncio
    async def test_create_new_version(self):
        """Create a new version of an existing skill."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Versioned Skill", version="1.0.0"))

        # Create version 2.0.0
        v2_spec = _make_skill_spec(name="Versioned Skill", version="2.0.0", description="Updated")
        v2_result = await registry.create_version(result["skill_id"], v2_spec)

        assert v2_result["version"] == "2.0.0"

        # Active version should be 2.0.0
        skill = await registry.get_skill(result["skill_id"])
        assert skill["active_version"]["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_activate_old_version(self):
        """Activate an older version (rollback)."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Rollback Skill", version="1.0.0"))

        # Create and activate v2
        v2_spec = _make_skill_spec(name="Rollback Skill", version="2.0.0")
        await registry.create_version(result["skill_id"], v2_spec)

        # Rollback to v1
        activated = await registry.activate_version(result["skill_id"], "1.0.0")
        assert activated

        skill = await registry.get_skill(result["skill_id"])
        assert skill["active_version"]["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_create_version_skill_not_found(self):
        """Creating a version for non-existent skill raises error."""
        registry = SkillRegistry()
        with pytest.raises(SkillNotFoundError):
            await registry.create_version("nonexistent", _make_skill_spec())

    @pytest.mark.asyncio
    async def test_get_active_version_spec(self):
        """Get the SkillSpec from the active version."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Spec Skill"))

        spec = await registry.get_active_version_spec(result["skill_id"])
        assert spec is not None
        assert spec.name == "Spec Skill"
        assert spec.version == "1.0.0"


class TestSkillUsageMetrics:
    """Test usage metric tracking."""

    @pytest.mark.asyncio
    async def test_record_usage(self):
        """Record usage updates metrics."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Used Skill"))

        await registry.record_usage(result["skill_id"], success=True, duration_seconds=10.0, cost=0.05)
        await registry.record_usage(result["skill_id"], success=True, duration_seconds=20.0, cost=0.15)

        skill = await registry.get_skill(result["skill_id"])
        assert skill["usage_count"] == 2
        assert skill["success_count"] == 2
        assert skill["avg_duration_seconds"] == 15.0  # (10+20)/2
        assert skill["avg_cost"] == 0.1  # (0.05+0.15)/2

    @pytest.mark.asyncio
    async def test_record_failure(self):
        """Record a failed usage."""
        registry = SkillRegistry()
        result = await registry.create_skill(_make_skill_spec(name="Failed Skill"))

        await registry.record_usage(result["skill_id"], success=False, duration_seconds=5.0)

        skill = await registry.get_skill(result["skill_id"])
        assert skill["usage_count"] == 1
        assert skill["failure_count"] == 1
        assert skill["success_count"] == 0