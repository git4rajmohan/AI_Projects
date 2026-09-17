"""Skill execution — runs a saved skill as a workflow.

Matches instruction.md section 11 (Skill Discovery) and Phase 5 acceptance:
"Successful workflow can be saved as a skill and reused."

When a skill is run:
1. Load the SkillSpec from the registry (active version)
2. Reconstruct a PlanSpec from the skill's spec_data
3. Create an execution record
4. Launch the orchestrator
5. Record usage metrics after completion
"""

import logging
from typing import Any

from app.models.agent import AgentSpec
from app.models.plan_schema import EvaluationSpec, MemorySpec, PlanSpec, WorkflowSpec
from app.models.skill_schema import SkillSpec
from app.orchestrator.engine import get_orchestrator
from app.orchestrator.state import get_state_manager
from app.skills.registry import SkillNotFoundError, get_skill_registry

logger = logging.getLogger(__name__)


class SkillExecutionError(Exception):
    """Raised when skill execution fails."""


def skill_to_plan_spec(skill_spec: SkillSpec, task_id: str, agent_specs: list[AgentSpec]) -> PlanSpec:
    """Reconstruct a PlanSpec from a SkillSpec.

    The skill stores agent IDs and tool IDs, but the full agent specs
    (name, goal, system_prompt, etc.) need to be provided separately.
    In the future, the skill YAML will contain full agent definitions.

    Args:
        skill_spec: The skill to convert.
        task_id: The task ID for the new execution.
        agent_specs: Full agent specifications (from the skill's stored plan data).

    Returns:
        A PlanSpec ready for orchestration.
    """
    return PlanSpec(
        task_id=task_id,
        objective=skill_spec.description,
        summary=f"Executing skill: {skill_spec.name}",
        agents=agent_specs,
        workflow=WorkflowSpec(**skill_spec.workflow) if skill_spec.workflow else WorkflowSpec(),
        memory=MemorySpec(),
        evaluation=EvaluationSpec(**skill_spec.evaluation) if skill_spec.evaluation else EvaluationSpec(),
        permissions=skill_spec.permissions,
        estimated_cost=0.0,
        estimated_duration_seconds=60,
        requires_approval=False,  # Skills are pre-approved by the user
    )


async def run_skill(
    skill_id: str,
    task_id: str,
    intent: str = "",
) -> dict[str, Any]:
    """Run a saved skill as a workflow.

    1. Load the skill's active version
    2. Reconstruct the plan from stored spec_data
    3. Create an execution record
    4. Launch the orchestrator in the background
    5. Return the execution ID

    Args:
        skill_id: The skill to run.
        task_id: The task ID to associate with this execution.
        intent: Optional override intent (defaults to skill description).

    Returns:
        Dict with execution_id, skill_id, and status.

    Raises:
        SkillExecutionError: If the skill doesn't exist or has no active version.
    """
    registry = get_skill_registry()

    # Load skill
    skill_data = await registry.get_skill(skill_id)
    if skill_data is None:
        raise SkillExecutionError(f"Skill '{skill_id}' not found")

    if not skill_data.get("enabled", True):
        raise SkillExecutionError(f"Skill '{skill_id}' is disabled")

    active_version = skill_data.get("active_version")
    if active_version is None:
        raise SkillExecutionError(f"Skill '{skill_id}' has no active version")

    spec_data = active_version.get("spec_data", {})

    # Reconstruct agent specs from spec_data
    # Check for "agent_definitions" (from imported skills with full agent specs)
    # or "agents" (which may contain full dicts from skill creation)
    agent_specs: list[AgentSpec] = []
    agent_definitions = spec_data.get("agent_definitions", [])

    if agent_definitions:
        # Imported skill with full agent definitions stored separately
        for agent_data in agent_definitions:
            try:
                agent_specs.append(AgentSpec(**agent_data))
            except Exception as e:
                raise SkillExecutionError(f"Failed to reconstruct agent from skill data: {e}")
    else:
        # Check if agents contains full dicts (from skill creation) or just IDs
        for agent_data in spec_data.get("agents", []):
            if isinstance(agent_data, dict):
                try:
                    agent_specs.append(AgentSpec(**agent_data))
                except Exception as e:
                    raise SkillExecutionError(f"Failed to reconstruct agent from skill data: {e}")

    if not agent_specs:
        raise SkillExecutionError(f"Skill '{skill_id}' has no agents defined")

    # Reconstruct SkillSpec
    skill_spec = SkillSpec(**spec_data)

    # Reconstruct PlanSpec
    plan_spec = skill_to_plan_spec(skill_spec, task_id, agent_specs)

    # Create execution record
    state_manager = get_state_manager()
    state = await state_manager.create_execution(
        task_id=task_id,
        plan_id=skill_id,  # Use skill_id as plan_id reference
    )

    # Launch orchestrator in the background
    orchestrator = get_orchestrator()

    async def _run():
        try:
            result = await orchestrator.execute(
                plan=plan_spec,
                task_id=task_id,
                execution_id=state.execution_id,
                intent=intent or skill_spec.description,
            )

            # Record usage metrics
            await registry.record_usage(
                skill_id=skill_id,
                success=result.status == "completed",
                duration_seconds=(
                    (result.completed_at - result.started_at).total_seconds()
                    if result.started_at and result.completed_at
                    else 0.0
                ),
            )
        except Exception as e:
            logger.error(f"Skill execution failed: {e}", exc_info=True)
            await registry.record_usage(skill_id=skill_id, success=False)

    import asyncio

    asyncio.create_task(_run())

    logger.info(f"Started skill '{skill_id}' execution {state.execution_id}")
    return {
        "execution_id": state.execution_id,
        "skill_id": skill_id,
        "skill_name": skill_data.get("name", ""),
        "status": "running",
    }