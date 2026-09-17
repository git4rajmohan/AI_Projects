"""Tests for skill creation from plans and skill-to-plan conversion.

Matches instruction.md section 25 (Skill Creation) and section 26 (Skill Content).
"""

import pytest

from app.models.agent import AgentSpec
from app.models.plan_schema import EvaluationSpec, PlanSpec, WorkflowSpec
from app.skills.creation import SkillCreationError, create_skill_from_plan, plan_to_skill_spec
from app.skills.registry import get_skill_registry


def _make_plan(agents: list[AgentSpec], **kwargs) -> PlanSpec:
    defaults = {
        "task_id": "task-123",
        "objective": "Test objective",
        "agents": agents,
    }
    defaults.update(kwargs)
    return PlanSpec(**defaults)


def _make_agent(id: str = "agent_1", tools: list[str] | None = None, deps: list[str] | None = None) -> AgentSpec:
    return AgentSpec(
        id=id,
        name=f"Agent {id}",
        goal=f"Goal of {id}",
        tools=tools or ["file_reader"],
        dependencies=deps or [],
    )


class TestPlanToSkillSpec:
    """Test converting a PlanSpec to a SkillSpec."""

    def test_basic_conversion(self):
        """Plan converts to a SkillSpec with correct fields."""
        plan = _make_plan([
            _make_agent("a", tools=["file_reader", "file_writer"]),
            _make_agent("b", tools=["python_executor"], deps=["a"]),
        ])

        spec = plan_to_skill_spec(plan, name="My Skill", description="Does things", tags=["tag1"])

        assert spec.name == "My Skill"
        assert spec.description == "Does things"
        assert spec.version == "1.0.0"
        assert set(spec.agents) == {"a", "b"}
        assert set(spec.tools) == {"file_reader", "file_writer", "python_executor"}
        assert "tag1" in spec.tags
        assert spec.enabled is True

    def test_workflow_preserved(self):
        """Workflow definition is preserved in the skill spec."""
        plan = _make_plan(
            [_make_agent("a")],
            workflow=WorkflowSpec(type="dag", nodes=[{"id": "a"}], edges=[]),
        )

        spec = plan_to_skill_spec(plan, name="Test", description="Test")
        assert spec.workflow["type"] == "dag"

    def test_evaluation_preserved(self):
        """Evaluation criteria are preserved."""
        plan = _make_plan(
            [_make_agent("a")],
            evaluation=EvaluationSpec(criteria=["accuracy", "completeness"], threshold=0.8),
        )

        spec = plan_to_skill_spec(plan, name="Test", description="Test")
        assert "accuracy" in spec.evaluation["criteria"]
        assert spec.evaluation["threshold"] == 0.8


class TestCreateSkillFromPlan:
    """Test creating a skill from a plan via the registry."""

    @pytest.mark.asyncio
    async def test_create_skill_from_plan(self):
        """A plan can be saved as a skill."""
        plan = _make_plan([
            _make_agent("researcher", tools=["web_search"]),
            _make_agent("writer", tools=["file_writer"], deps=["researcher"]),
        ])

        result = await create_skill_from_plan(
            plan,
            name="Research & Report",
            description="Research a topic and write a report",
            tags=["research", "report"],
            author="test",
        )

        assert "skill_id" in result
        assert result["version"] == "1.0.0"

        # Verify it's in the registry
        registry = get_skill_registry()
        skill = await registry.get_skill(result["skill_id"])
        assert skill is not None
        assert skill["name"] == "Research & Report"

    @pytest.mark.asyncio
    async def test_create_skill_empty_plan_raises(self):
        """Creating a skill from an empty plan raises an error."""
        plan = _make_plan([])

        with pytest.raises(SkillCreationError):
            await create_skill_from_plan(plan, name="Empty", description="No agents")