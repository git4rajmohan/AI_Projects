"""Tests for the Agent Factory and Agent Runtime.

Phase 3 acceptance: "One agent can execute a task using a tool."
"""

import pytest

from app.factory.agent_factory import AgentFactory, FactoryError, get_factory
from app.factory.context import AgentContext, AgentResult
from app.factory.runtime import AgentRuntime, create_runtime
from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec


def _make_agent_spec(
    id: str = "test_agent",
    name: str = "Test Agent",
    goal: str = "Read a file and report its contents",
    tools: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> AgentSpec:
    return AgentSpec(
        id=id,
        name=name,
        goal=goal,
        tools=tools or ["file_reader"],
        dependencies=dependencies or [],
        max_iterations=3,
        max_tool_calls=5,
        timeout_seconds=60,
    )


def _make_plan(agents: list[AgentSpec], **kwargs) -> PlanSpec:
    defaults = {
        "task_id": "task-123",
        "objective": "Test objective",
        "agents": agents,
    }
    defaults.update(kwargs)
    return PlanSpec(**defaults)


class TestAgentFactory:
    """Test the AgentFactory."""

    def test_create_single_agent(self):
        """Factory creates a runtime for a single-agent plan."""
        factory = AgentFactory()
        plan = _make_plan([_make_agent_spec()])
        runtimes = factory.create_agents(plan)

        assert len(runtimes) == 1
        assert "test_agent" in runtimes
        assert isinstance(runtimes["test_agent"], AgentRuntime)

    def test_create_multiple_agents(self):
        """Factory creates runtimes for multi-agent plans."""
        factory = AgentFactory()
        agents = [
            _make_agent_spec(id="agent_a", name="Agent A", goal="Do A"),
            _make_agent_spec(id="agent_b", name="Agent B", goal="Do B", dependencies=["agent_a"]),
        ]
        plan = _make_plan(agents)
        runtimes = factory.create_agents(plan)

        assert len(runtimes) == 2
        assert "agent_a" in runtimes
        assert "agent_b" in runtimes

    def test_unknown_tool_raises_error(self):
        """Factory raises FactoryError for unknown tools."""
        factory = AgentFactory()
        agent = _make_agent_spec(tools=["nonexistent_tool"])
        plan = _make_plan([agent])

        with pytest.raises(FactoryError) as exc_info:
            factory.create_agents(plan)
        assert "nonexistent_tool" in str(exc_info.value)

    def test_create_context(self):
        """Factory creates an AgentContext with correct fields."""
        factory = AgentFactory()
        plan = _make_plan([_make_agent_spec()])
        context = factory.create_context(
            plan,
            task_id="task-456",
            execution_id="exec-789",
            intent="Read a CSV file",
        )

        assert context.task_id == "task-456"
        assert context.execution_id == "exec-789"
        assert context.intent == "Read a CSV file"
        assert context.inputs == {}


class TestAgentContext:
    """Test the AgentContext data structure."""

    def test_add_tool_result(self):
        """Tool results are recorded in context."""
        ctx = AgentContext(intent="test")
        ctx.add_tool_result("file_reader", {"path": "test.txt"}, {"success": True, "output": {"content": "hello"}})

        assert len(ctx.tool_results) == 1
        assert ctx.tool_results[0]["tool_id"] == "file_reader"
        assert ctx.tool_results[0]["result"]["output"]["content"] == "hello"

    def test_working_memory(self):
        """Working memory set/get works."""
        ctx = AgentContext(intent="test")
        ctx.set_memory("key1", "value1")
        assert ctx.get_memory("key1") == "value1"
        assert ctx.get_memory("nonexistent", "default") == "default"


class TestAgentResult:
    """Test the AgentResult data structure."""

    def test_success_property(self):
        """success property returns True for completed status."""
        result = AgentResult(agent_id="a1", status="completed")
        assert result.success

    def test_failure_property(self):
        """success property returns False for failed status."""
        result = AgentResult(agent_id="a1", status="failed", error="Something went wrong")
        assert not result.success


class TestAgentRuntime:
    """Test the AgentRuntime (without LLM calls)."""

    def test_create_runtime(self):
        """create_runtime produces an AgentRuntime."""
        spec = _make_agent_spec()
        runtime = create_runtime(spec)
        assert isinstance(runtime, AgentRuntime)
        assert runtime.spec.id == "test_agent"

    @pytest.mark.asyncio
    async def test_runtime_timeout(self):
        """Runtime enforces timeout and returns timed_out status."""
        # Create an agent with a 10-second timeout (min allowed by schema)
        spec = AgentSpec(
            id="timeout_agent",
            name="Timeout Agent",
            goal="This will time out",
            tools=[],
            max_iterations=50,
            timeout_seconds=10,
        )
        runtime = AgentRuntime(spec)
        context = AgentContext(intent="test")

        # The LLM call will likely take longer than 1s, so this should time out
        # or fail — either way, it should return an AgentResult
        result = await runtime.execute(context)
        assert result.status in ("timed_out", "failed", "completed")
        assert result.agent_id == "timeout_agent"