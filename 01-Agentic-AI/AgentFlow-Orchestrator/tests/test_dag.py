"""Tests for the DAG engine — topological sorting and dependency resolution.

Matches instruction.md section 15 (Orchestration Engine).
"""

import pytest

from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec
from app.orchestrator.dag import DAGError, ExecutionDAG


def _make_agent(
    id: str = "agent_1",
    name: str = "Agent 1",
    goal: str = "Do something",
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


class TestDAGConstruction:
    """Test DAG building from plans."""

    def test_single_agent(self):
        """A single-agent plan produces a DAG with one node at level 0."""
        plan = _make_plan([_make_agent("solo")])
        dag = ExecutionDAG(plan)

        assert len(dag.nodes) == 1
        assert "solo" in dag.nodes
        assert dag.nodes["solo"].level == 0
        assert not dag.is_empty

    def test_sequential_chain(self):
        """A → B → C produces levels [A], [B], [C]."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("b", dependencies=["a"]),
            _make_agent("c", dependencies=["b"]),
        ])
        dag = ExecutionDAG(plan)

        levels = dag.get_execution_levels()
        assert len(levels) == 3
        assert levels[0] == ["a"]
        assert levels[1] == ["b"]
        assert levels[2] == ["c"]

    def test_parallel_agents(self):
        """Three independent agents are all at level 0 (parallel)."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("b"),
            _make_agent("c"),
        ])
        dag = ExecutionDAG(plan)

        levels = dag.get_execution_levels()
        assert len(levels) == 1
        assert set(levels[0]) == {"a", "b", "c"}

    def test_merge_pattern(self):
        """{A, B, C} → D: D waits for all three at level 1."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("b"),
            _make_agent("c"),
            _make_agent("d", dependencies=["a", "b", "c"]),
        ])
        dag = ExecutionDAG(plan)

        levels = dag.get_execution_levels()
        assert len(levels) == 2
        assert set(levels[0]) == {"a", "b", "c"}
        assert levels[1] == ["d"]

    def test_diamond_pattern(self):
        """A → {B, C} → D: classic diamond DAG."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("b", dependencies=["a"]),
            _make_agent("c", dependencies=["a"]),
            _make_agent("d", dependencies=["b", "c"]),
        ])
        dag = ExecutionDAG(plan)

        levels = dag.get_execution_levels()
        assert len(levels) == 3
        assert levels[0] == ["a"]
        assert set(levels[1]) == {"b", "c"}
        assert levels[2] == ["d"]

    def test_circular_dependency_raises(self):
        """A → B → A raises DAGError."""
        plan = _make_plan([
            _make_agent("a", dependencies=["b"]),
            _make_agent("b", dependencies=["a"]),
        ])
        with pytest.raises(DAGError, match="Circular dependency"):
            ExecutionDAG(plan)

    def test_missing_dependency_raises(self):
        """Agent depending on non-existent agent raises DAGError."""
        plan = _make_plan([
            _make_agent("a", dependencies=["nonexistent"]),
        ])
        with pytest.raises(DAGError, match="unknown agent"):
            ExecutionDAG(plan)

    def test_duplicate_agent_id_raises(self):
        """Duplicate agent IDs raise DAGError."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("a"),
        ])
        with pytest.raises(DAGError, match="Duplicate agent ID"):
            ExecutionDAG(plan)


class TestDAGQueries:
    """Test DAG query methods."""

    def test_get_ready_agents(self):
        """get_ready_agents returns agents whose deps are all completed."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("b", dependencies=["a"]),
            _make_agent("c", dependencies=["a"]),
            _make_agent("d", dependencies=["b", "c"]),
        ])
        dag = ExecutionDAG(plan)

        # Initially, only "a" is ready
        ready = dag.get_ready_agents(set())
        assert ready == ["a"]

        # After "a" completes, "b" and "c" are ready
        ready = dag.get_ready_agents({"a"})
        assert set(ready) == {"b", "c"}

        # After "b" and "c" complete, "d" is ready
        ready = dag.get_ready_agents({"a", "b", "c"})
        assert ready == ["d"]

        # After all complete, nothing is ready
        ready = dag.get_ready_agents({"a", "b", "c", "d"})
        assert ready == []

    def test_get_dependencies(self):
        """get_dependencies returns the set of dependency IDs."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("b", dependencies=["a"]),
        ])
        dag = ExecutionDAG(plan)

        assert dag.get_dependencies("a") == set()
        assert dag.get_dependencies("b") == {"a"}

    def test_get_agent(self):
        """get_agent returns the AgentSpec."""
        plan = _make_plan([_make_agent("a", name="My Agent")])
        dag = ExecutionDAG(plan)

        spec = dag.get_agent("a")
        assert spec.name == "My Agent"

    def test_agent_ids(self):
        """agent_ids returns all agent IDs."""
        plan = _make_plan([
            _make_agent("a"),
            _make_agent("b"),
        ])
        dag = ExecutionDAG(plan)

        assert set(dag.agent_ids) == {"a", "b"}

    def test_empty_plan(self):
        """An empty plan produces an empty DAG."""
        plan = _make_plan([])
        dag = ExecutionDAG(plan)

        assert dag.is_empty
        assert dag.get_execution_levels() == []