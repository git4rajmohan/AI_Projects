"""Skill creation — converts a successful execution into a reusable skill.

Matches instruction.md section 25 (Skill Creation) and section 26 (Skill Content).

After a successful execution, the system can save the workflow as a skill:
1. Extract the plan's agent specs, tools, workflow, evaluation
2. Create a SkillSpec from the plan data
3. Store it in the Skill Registry with version 1.0.0

The user must approve skill creation (MVP: do not auto-persist).
"""

import logging
from typing import Any

from app.models.plan_schema import PlanSpec
from app.models.skill_schema import SkillSpec
from app.skills.registry import SkillRegistry, get_skill_registry

logger = logging.getLogger(__name__)


class SkillCreationError(Exception):
    """Raised when skill creation fails."""


def plan_to_skill_spec(
    plan: PlanSpec,
    name: str,
    description: str,
    tags: list[str] | None = None,
    author: str | None = None,
) -> SkillSpec:
    """Convert a PlanSpec into a SkillSpec.

    Extracts:
    - Agent IDs and tool IDs from the plan
    - Workflow definition
    - Evaluation criteria
    - Permissions

    Args:
        plan: The successful plan to convert.
        name: Human-readable skill name.
        description: What the skill does.
        tags: Optional tags for discovery.
        author: Optional author name.

    Returns:
        A SkillSpec ready to be saved to the registry.
    """
    agent_ids = [a.id for a in plan.agents]
    tool_ids: set[str] = set()
    for agent in plan.agents:
        tool_ids.update(agent.tools)

    return SkillSpec(
        id="",  # Will be assigned by the registry
        name=name,
        description=description,
        version="1.0.0",
        inputs={},  # Can be inferred from first agent's input_schema
        outputs={},  # Can be inferred from last agent's output_schema
        agents=agent_ids,
        tools=list(tool_ids),
        workflow=plan.workflow.model_dump(),
        evaluation=plan.evaluation.model_dump(),
        permissions=plan.permissions,
        author=author,
        tags=tags or [],
        enabled=True,
    )


async def create_skill_from_plan(
    plan: PlanSpec,
    name: str,
    description: str,
    tags: list[str] | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    """Create a reusable skill from a successful plan.

    Args:
        plan: The successful plan to save as a skill.
        name: Human-readable skill name.
        description: What the skill does.
        tags: Optional tags for discovery.
        author: Optional author name.

    Returns:
        Dict with skill_id, version_id, and version.

    Raises:
        SkillCreationError: If the plan has no agents or creation fails.
    """
    if not plan.agents:
        raise SkillCreationError("Cannot create skill from plan with no agents")

    spec = plan_to_skill_spec(plan, name, description, tags, author)

    registry = get_skill_registry()
    result = await registry.create_skill(spec, author=author)

    logger.info(
        f"Created skill '{name}' from plan (task_id={plan.task_id}, "
        f"agents={len(spec.agents)}, tools={len(spec.tools)})"
    )

    return result