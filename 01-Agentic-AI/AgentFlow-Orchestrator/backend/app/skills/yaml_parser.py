"""Skill YAML parser and validator.

Matches instruction.md section 29 (Skill YAML Format) and section 30 (Skill Validation).

Parses skill.yaml files into SkillSpec objects and validates:
- Required fields (name, description, version, agents)
- Tool references exist in the registry
- Agent definitions are valid
- Version is semantic (x.y.z)
- Workflow type is supported
"""

import logging
from typing import Any

import yaml

from app.models.agent import AgentSpec
from app.models.skill_schema import SkillSpec
from app.tools.registry import get_registry

logger = logging.getLogger(__name__)


class SkillValidationError(Exception):
    """Raised when a skill YAML fails validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Skill validation failed: {'; '.join(errors)}")


def parse_skill_yaml(yaml_content: str) -> dict[str, Any]:
    """Parse a skill YAML string into a dict.

    Args:
        yaml_content: The YAML content as a string.

    Returns:
        Parsed dict.

    Raises:
        SkillValidationError: If the YAML is invalid.
    """
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise SkillValidationError([f"Invalid YAML: {e}"])

    if not isinstance(data, dict):
        raise SkillValidationError(["Skill YAML must be a mapping/dict"])

    return data


def yaml_to_skill_spec(data: dict[str, Any]) -> SkillSpec:
    """Convert a parsed YAML dict into a SkillSpec.

    Handles the YAML format from instruction.md section 29, which uses
    a richer format than the basic SkillSpec (with full agent definitions).

    Args:
        data: Parsed YAML dict.

    Returns:
        A SkillSpec.

    Raises:
        SkillValidationError: If required fields are missing.
    """
    errors: list[str] = []

    # Required fields
    name = data.get("name")
    if not name:
        errors.append("Missing required field: name")

    description = data.get("description", "")
    if not description:
        errors.append("Missing required field: description")

    version = data.get("version", "1.0.0")

    # Validate semantic versioning
    if not _is_valid_semver(version):
        errors.append(f"Invalid version format: '{version}' (expected x.y.z)")

    # Parse agents — can be a list of strings (IDs) or list of dicts (full specs)
    agent_data = data.get("agents", [])
    agent_ids: list[str] = []
    if isinstance(agent_data, list):
        for item in agent_data:
            if isinstance(item, str):
                agent_ids.append(item)
            elif isinstance(item, dict):
                agent_id = item.get("id")
                if agent_id:
                    agent_ids.append(agent_id)

    # Parse tools
    tools = data.get("tools", [])
    if not isinstance(tools, list):
        tools = []

    # Parse workflow
    workflow = data.get("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {"type": "dag"}

    # Validate workflow type
    wf_type = workflow.get("type", "dag")
    if wf_type not in ("dag", "sequential", "parallel"):
        errors.append(f"Invalid workflow type: '{wf_type}' (expected dag, sequential, or parallel)")

    # Parse evaluation
    evaluation = data.get("evaluation", {})
    if not isinstance(evaluation, dict):
        evaluation = {}

    # Parse permissions
    permissions = data.get("permissions", {})
    if not isinstance(permissions, dict):
        permissions = {}

    # Parse tags
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    # Parse inputs/outputs
    inputs = data.get("inputs", [])
    outputs = data.get("outputs", [])

    if errors:
        raise SkillValidationError(errors)

    return SkillSpec(
        id="",  # Assigned by registry
        name=name,
        description=description.strip() if isinstance(description, str) else str(description),
        version=version,
        inputs=_io_to_dict(inputs),
        outputs=_io_to_dict(outputs),
        agents=agent_ids,
        tools=tools,
        workflow=workflow,
        evaluation=evaluation,
        permissions=permissions,
        author=data.get("author"),
        tags=tags,
        enabled=data.get("enabled", True),
    )


def parse_agent_specs_from_yaml(data: dict[str, Any]) -> list[AgentSpec]:
    """Extract full AgentSpec objects from the YAML data.

    The YAML format supports full agent definitions with id, name, goal, tools, etc.
    This extracts them for use in skill execution.

    Args:
        data: Parsed YAML dict.

    Returns:
        List of AgentSpec objects. Returns empty list if agents are just string IDs.
    """
    agent_data = data.get("agents", [])
    specs: list[AgentSpec] = []

    if not isinstance(agent_data, list):
        return specs

    for item in agent_data:
        if isinstance(item, dict):
            try:
                spec = AgentSpec(
                    id=item.get("id", ""),
                    name=item.get("name", item.get("id", "Unknown")),
                    description=item.get("description", ""),
                    goal=item.get("goal", ""),
                    tools=item.get("tools", []),
                    dependencies=item.get("dependencies", []),
                    max_iterations=item.get("max_iterations", 5),
                    max_tool_calls=item.get("max_tool_calls", 20),
                    timeout_seconds=item.get("timeout_seconds", 300),
                    requires_human_approval=item.get("requires_human_approval", False),
                )
                if spec.id:
                    specs.append(spec)
            except Exception as e:
                logger.warning(f"Failed to parse agent from YAML: {e}")

    return specs


def validate_skill(
    spec: SkillSpec,
    agent_specs: list[AgentSpec] | None = None,
    check_tools: bool = True,
) -> list[str]:
    """Validate a SkillSpec and return a list of issues (empty = valid).

    Checks:
    - Required fields (name, description, agents)
    - Version is semantic
    - All referenced tools exist in the registry (if check_tools=True)
    - All agent IDs in spec.agents have corresponding AgentSpecs (if agent_specs provided)
    - No duplicate agent IDs

    Args:
        spec: The SkillSpec to validate.
        agent_specs: Optional full agent specs for validation.
        check_tools: If True, verify tools exist in the registry.

    Returns:
        List of validation issue strings (empty = valid).
    """
    issues: list[str] = []

    # Required fields
    if not spec.name:
        issues.append("Skill name is required")
    if not spec.description:
        issues.append("Skill description is required")
    if not spec.agents:
        issues.append("Skill must have at least one agent")

    # Version
    if not _is_valid_semver(spec.version):
        issues.append(f"Invalid version: '{spec.version}' (expected x.y.z)")

    # Tools exist in registry
    if check_tools:
        registry = get_registry()
        for tool_id in spec.tools:
            if not registry.has(tool_id):
                issues.append(f"Unknown tool: '{tool_id}'")

    # Agent specs validation
    if agent_specs:
        agent_ids = [a.id for a in agent_specs]
        # Check for duplicates
        if len(agent_ids) != len(set(agent_ids)):
            issues.append("Duplicate agent IDs in skill")

        # Check all spec.agents have corresponding AgentSpecs
        for agent_id in spec.agents:
            if agent_id not in agent_ids:
                issues.append(f"Agent '{agent_id}' has no full definition")

        # Check dependencies reference valid agents
        for agent in agent_specs:
            for dep in agent.dependencies:
                if dep not in agent_ids:
                    issues.append(f"Agent '{agent.id}' depends on unknown agent '{dep}'")

    return issues


def _is_valid_semver(version: str) -> bool:
    """Check if a version string is valid semantic versioning (x.y.z)."""
    if not version:
        return False
    parts = version.split(".")
    if len(parts) < 2:
        return False
    try:
        # Allow pre-release suffixes (e.g., 1.0.0-beta)
        for part in parts[:3]:
            int(part.split("-")[0].split("+")[0])
        return True
    except ValueError:
        return False


def _io_to_dict(io_list: list) -> dict:
    """Convert a list of input/output definitions to a dict.

    Example:
        [{"name": "input_file", "type": "file"}]
        → {"input_file": {"type": "file"}}
    """
    result: dict[str, Any] = {}
    if not isinstance(io_list, list):
        return result
    for item in io_list:
        if isinstance(item, dict) and "name" in item:
            name = item["name"]
            result[name] = {k: v for k, v in item.items() if k != "name"}
    return result