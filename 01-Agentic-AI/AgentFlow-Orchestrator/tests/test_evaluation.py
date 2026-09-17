"""Tests for the Evaluation Engine.

Matches instruction.md section 23 (Evaluation Engine).
"""

import pytest

from app.evaluation.engine import EvaluationEngine, get_evaluation_engine
from app.models.agent import AgentSpec
from app.models.evaluation import EvaluationResult
from app.models.plan_schema import EvaluationSpec, PlanSpec
from app.orchestrator.state import ExecutionState


def _make_plan(
    agents: list[AgentSpec] | None = None,
    criteria: list[str] | None = None,
    threshold: float = 0.7,
) -> PlanSpec:
    return PlanSpec(
        task_id="task-eval-1",
        objective="Test objective",
        agents=agents or [AgentSpec(id="a1", name="Agent 1", goal="Test")],
        evaluation=EvaluationSpec(criteria=criteria or ["completeness", "accuracy"], threshold=threshold),
    )


def _make_state(
    status: str = "completed",
    completed: list[str] | None = None,
    failed: list[str] | None = None,
    outputs: dict | None = None,
) -> ExecutionState:
    state = ExecutionState(
        execution_id="exec-eval-1",
        task_id="task-eval-1",
        plan_id="plan-eval-1",
    )
    state.status = status
    state.completed_nodes = completed if completed is not None else ["a1"]
    state.failed_nodes = failed if failed is not None else []
    state.outputs = outputs if outputs is not None else {"a1": {"response": "result"}}
    return state


class TestEvaluationEngine:
    """Test the EvaluationEngine."""

    @pytest.mark.asyncio
    async def test_successful_execution_passes(self):
        """A completed execution with all agents passing evaluates as success."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan()
        state = _make_state(status="completed", completed=["a1"])

        result = await engine.evaluate(plan, state, intent="Test intent")

        assert result.success
        assert result.score > 0
        assert "completeness" in result.criteria
        assert "accuracy" in result.criteria

    @pytest.mark.asyncio
    async def test_failed_execution_fails(self):
        """A failed execution evaluates as failure."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan()
        state = _make_state(status="failed", completed=[], failed=["a1"])

        result = await engine.evaluate(plan, state, intent="Test intent")

        assert not result.success
        assert result.score < plan.evaluation.threshold

    @pytest.mark.asyncio
    async def test_partial_completion(self):
        """Only some agents completing gives a partial score."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan(agents=[
            AgentSpec(id="a1", name="A1", goal="G1"),
            AgentSpec(id="a2", name="A2", goal="G2"),
        ])
        state = _make_state(status="completed", completed=["a1"], failed=["a2"])

        result = await engine.evaluate(plan, state, intent="Test")

        # Completeness should be 0.5 (1 of 2 agents)
        assert result.criteria["completeness"] == 0.5
        assert not result.success  # Below threshold due to failure

    @pytest.mark.asyncio
    async def test_empty_outputs_flagged(self):
        """Empty outputs are flagged as an issue."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan()
        state = _make_state(status="completed", completed=["a1"], outputs={"a1": {}})

        result = await engine.evaluate(plan, state, intent="Test")

        assert any("empty output" in issue.lower() for issue in result.issues)

    @pytest.mark.asyncio
    async def test_threshold_respected(self):
        """Evaluation respects the threshold from the plan."""
        engine = EvaluationEngine(use_llm=False)
        # Maximum threshold with format criterion — empty output means format=0
        plan = _make_plan(criteria=["completeness", "accuracy", "format"], threshold=1.0)
        state = _make_state(status="completed", completed=["a1"], outputs={"a1": {}})

        result = await engine.evaluate(plan, state, intent="Test")

        # format score = 0 (empty output), so overall < 1.0
        assert not result.success

    @pytest.mark.asyncio
    async def test_format_criterion(self):
        """Format criterion scores based on non-empty outputs."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan(criteria=["format"])
        state = _make_state(
            status="completed",
            completed=["a1", "a2"],
            outputs={"a1": {"result": "data"}, "a2": {}},
        )

        result = await engine.evaluate(plan, state, intent="Test")

        # 1 of 2 outputs is non-empty → format score = 0.5
        assert result.criteria["format"] == 0.5

    @pytest.mark.asyncio
    async def test_relevance_criterion(self):
        """Relevance criterion scores 1.0 if output exists."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan(criteria=["relevance"])
        state = _make_state(status="completed", outputs={"a1": {"data": "yes"}})

        result = await engine.evaluate(plan, state, intent="Test")

        assert result.criteria["relevance"] == 1.0

    @pytest.mark.asyncio
    async def test_no_outputs_relevance_zero(self):
        """Relevance is 0.0 when no outputs."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan(criteria=["relevance"])
        state = _make_state(status="completed", completed=[], outputs={})

        result = await engine.evaluate(plan, state, intent="Test")

        assert result.criteria["relevance"] == 0.0

    @pytest.mark.asyncio
    async def test_unknown_criterion_defaults_to_success(self):
        """Unknown criteria default to 1.0 for completed executions."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan(criteria=["custom_criterion"])
        state = _make_state(status="completed")

        result = await engine.evaluate(plan, state, intent="Test")

        assert result.criteria["custom_criterion"] == 1.0

    @pytest.mark.asyncio
    async def test_recommendations_present_on_failure(self):
        """Failed evaluations have issues listed."""
        engine = EvaluationEngine(use_llm=False)
        plan = _make_plan()
        state = _make_state(status="failed", completed=[], failed=["a1"])

        result = await engine.evaluate(plan, state, intent="Test")

        assert len(result.issues) > 0

    @pytest.mark.asyncio
    async def test_get_evaluation_engine_singleton(self):
        """get_evaluation_engine returns a singleton."""
        engine1 = get_evaluation_engine()
        engine2 = get_evaluation_engine()
        assert engine1 is engine2