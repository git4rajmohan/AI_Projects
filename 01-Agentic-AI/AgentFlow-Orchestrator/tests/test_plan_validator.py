"""Tests for the plan validator."""

import pytest

from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec
from app.planner.plan_validator import (
    PlanValidationError,
    validate_plan,
    validate_plan_json,
)


def _make_agent(
    id: str = "agent_1",
    name: str = "Test Agent",
    goal: str = "Test goal",
    dependencies: list[str] | None = None,
) -> AgentSpec:
    return AgentSpec(
        id=id,
        name=name,
        goal=goal,
        dependencies=dependencies or [],
    )


def _make_plan(agents: list[AgentSpec], **kwargs) -> PlanSpec:
    defaults = {
        "task_id": "task-123",
        "objective": "Test objective",
        "agents": agents,
    }
    defaults.update(kwargs)
    return PlanSpec(**defaults)


class TestPlanValidation:
    """Test plan validation rules."""

    def test_valid_simple_plan(self):
        """A plan with one agent and no dependencies is valid."""
        plan = _make_plan([_make_agent()])
        issues = validate_plan(plan)
        assert issues == []

    def test_valid_multi_agent_plan(self):
        """A plan with multiple agents and valid dependencies is valid."""
        plan = _make_plan([
            _make_agent(id="a1", name="Agent 1"),
            _make_agent(id="a2", name="Agent 2", dependencies=["a1"]),
            _make_agent(id="a3", name="Agent 3", dependencies=["a1"]),
        ])
        issues = validate_plan(plan)
        assert issues == []

    def test_empty_agents_fails(self):
        """A plan with no agents fails validation."""
        plan = _make_plan([])
        issues = validate_plan(plan)
        assert len(issues) == 1
        assert "at least one agent" in issues[0]

    def test_duplicate_agent_ids_fails(self):
        """Duplicate agent IDs fail validation."""
        plan = _make_plan([
            _make_agent(id="dup", name="Agent 1"),
            _make_agent(id="dup", name="Agent 2"),
        ])
        issues = validate_plan(plan)
        assert any("unique" in i for i in issues)

    def test_invalid_dependency_fails(self):
        """Dependency on non-existent agent fails."""
        plan = _make_plan([
            _make_agent(id="a1", dependencies=["nonexistent"]),
        ])
        issues = validate_plan(plan)
        assert any("nonexistent" in i for i in issues)

    def test_circular_dependency_fails(self):
        """Circular dependencies are detected."""
        plan = _make_plan([
            _make_agent(id="a1", dependencies=["a2"]),
            _make_agent(id="a2", dependencies=["a1"]),
        ])
        issues = validate_plan(plan)
        assert any("Circular" in i for i in issues)


class TestPlanJsonValidation:
    """Test JSON-to-PlanSpec validation."""

    def test_valid_json_returns_plan(self):
        """Valid JSON converts to PlanSpec."""
        plan_data = {
            "objective": "Test objective",
            "summary": "Test summary",
            "agents": [
                {"id": "a1", "name": "Agent 1", "goal": "Do something"}
            ],
        }
        plan = validate_plan_json(plan_data, "task-123")
        assert plan.task_id == "task-123"
        assert plan.objective == "Test objective"
        assert len(plan.agents) == 1
        assert plan.agents[0].id == "a1"

    def test_missing_agents_fails(self):
        """JSON without agents fails."""
        plan_data = {"objective": "Test"}
        with pytest.raises(PlanValidationError):
            validate_plan_json(plan_data, "task-123")

    def test_missing_objective_fails(self):
        """JSON without objective fails."""
        plan_data = {"agents": [{"id": "a1", "name": "A1", "goal": "G"}]}
        with pytest.raises(PlanValidationError):
            validate_plan_json(plan_data, "task-123")

    def test_task_id_is_injected(self):
        """task_id is injected from the parameter, not from JSON."""
        plan_data = {
            "objective": "Test",
            "agents": [{"id": "a1", "name": "A1", "goal": "G"}],
        }
        plan = validate_plan_json(plan_data, "injected-task-id")
        assert plan.task_id == "injected-task-id"