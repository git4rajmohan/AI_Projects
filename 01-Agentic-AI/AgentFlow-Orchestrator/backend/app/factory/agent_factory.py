"""Agent Factory — creates executable agents from a plan.

Matches instruction.md section 14 (Agent Runtime) and Phase 3 acceptance:
"One agent can execute a task using a tool."

The factory:
1. Takes a PlanSpec
2. Creates AgentRuntime instances for each agent in the plan
3. Validates that all referenced tools exist in the registry
4. Returns a dict of agent_id → AgentRuntime
"""

import logging
from typing import Any

from app.factory.context import AgentContext
from app.factory.runtime import AgentRuntime, create_runtime
from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec
from app.tools.registry import ToolNotFoundError, get_registry

logger = logging.getLogger(__name__)


class FactoryError(Exception):
    """Raised when the factory cannot create agents from a plan."""


class AgentFactory:
    """Creates executable agents from a PlanSpec.

    Usage:
        factory = AgentFactory()
        runtimes = factory.create_agents(plan)
        result = await runtimes["agent_1"].execute(context)
    """

    def __init__(self) -> None:
        self._registry = get_registry()

    def create_agents(self, plan: PlanSpec) -> dict[str, AgentRuntime]:
        """Create AgentRuntime instances for all agents in the plan.

        Args:
            plan: The PlanSpec containing agent definitions.

        Returns:
            Dict mapping agent_id → AgentRuntime.

        Raises:
            FactoryError: If any agent references unknown tools.
        """
        runtimes: dict[str, AgentRuntime] = {}

        for agent_spec in plan.agents:
            # Validate tools exist
            missing_tools = []
            for tool_id in agent_spec.tools:
                if not self._registry.has(tool_id):
                    missing_tools.append(tool_id)

            if missing_tools:
                raise FactoryError(
                    f"Agent '{agent_spec.id}' references unknown tools: {missing_tools}. "
                    f"Available: {[t.id for t in self._registry.list()]}"
                )

            # Create runtime
            runtime = create_runtime(agent_spec)
            runtimes[agent_spec.id] = runtime
            logger.info(f"Created agent runtime: {agent_spec.id} ({agent_spec.name})")

        logger.info(f"Factory created {len(runtimes)} agents for plan")
        return runtimes

    def create_context(
        self,
        plan: PlanSpec,
        task_id: str = "",
        execution_id: str = "",
        intent: str = "",
        dependency_outputs: dict[str, Any] | None = None,
    ) -> AgentContext:
        """Create an AgentContext for execution.

        Args:
            plan: The plan being executed.
            task_id: The parent task ID.
            execution_id: The execution instance ID.
            intent: The original user intent.
            dependency_outputs: Outputs from upstream agents (agent_id → output).

        Returns:
            An AgentContext ready for execution.
        """
        return AgentContext(
            task_id=task_id,
            execution_id=execution_id,
            intent=intent or plan.objective,
            inputs=dependency_outputs or {},
            working_memory={},
        )


# --- Singleton ---

_factory: AgentFactory | None = None


def get_factory() -> AgentFactory:
    """Get the singleton AgentFactory instance."""
    global _factory
    if _factory is None:
        _factory = AgentFactory()
    return _factory