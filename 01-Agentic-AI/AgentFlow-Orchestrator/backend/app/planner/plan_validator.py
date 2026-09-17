"""Plan validation — validates a PlanSpec against business rules.

Matches instruction.md section 9 (Plan Model) and section 49 (Architectural Rules).
"""

from pydantic import ValidationError

from app.models.plan_schema import PlanSpec


class PlanValidationError(Exception):
    """Raised when a plan fails validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Plan validation failed: {'; '.join(errors)}")


def validate_plan(plan: PlanSpec) -> list[str]:
    """Validate a PlanSpec and return a list of issues (empty = valid).

    Checks:
    - At least one agent
    - All agent IDs are unique
    - All dependencies reference existing agent IDs
    - No circular dependencies
    - Workflow edges reference valid agent IDs
    """
    issues: list[str] = []

    # Must have at least one agent
    if not plan.agents:
        issues.append("Plan must have at least one agent")
        return issues

    # Agent IDs must be unique
    agent_ids = [a.id for a in plan.agents]
    if len(agent_ids) != len(set(agent_ids)):
        issues.append("Agent IDs must be unique")

    # Dependencies must reference valid agent IDs
    for agent in plan.agents:
        for dep in agent.dependencies:
            if dep not in agent_ids:
                issues.append(f"Agent '{agent.id}' depends on unknown agent '{dep}'")

    # Check for circular dependencies
    cycles = _detect_cycles(plan)
    if cycles:
        issues.append(f"Circular dependencies detected: {cycles}")

    # Workflow edges must reference valid agent IDs
    for edge in plan.workflow.edges:
        source = edge.get("source", edge.get("from", ""))
        target = edge.get("target", edge.get("to", ""))
        if source and source not in agent_ids and source != "START":
            issues.append(f"Workflow edge source '{source}' is not a valid agent ID")
        if target and target not in agent_ids and target != "END":
            issues.append(f"Workflow edge target '{target}' is not a valid agent ID")

    return issues


def validate_plan_or_raise(plan: PlanSpec) -> None:
    """Validate a plan and raise PlanValidationError if invalid."""
    issues = validate_plan(plan)
    if issues:
        raise PlanValidationError(issues)


def validate_plan_json(plan_data: dict, task_id: str) -> PlanSpec:
    """Validate raw plan JSON dict and return a PlanSpec.

    Args:
        plan_data: Raw plan data from LLM output.
        task_id: Task ID to inject (LLM doesn't know this).

    Returns:
        Validated PlanSpec.

    Raises:
        PlanValidationError: If the plan is invalid.
    """
    issues: list[str] = []

    # Inject task_id
    plan_data["task_id"] = task_id

    # Ensure matched_skills exists
    if "matched_skills" not in plan_data:
        plan_data["matched_skills"] = []

    try:
        plan = PlanSpec.model_validate(plan_data)
    except ValidationError as e:
        # Extract human-readable errors
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            issues.append(f"{loc}: {err['msg']}")
        raise PlanValidationError(issues)

    # Run business rule validation
    issues = validate_plan(plan)
    if issues:
        raise PlanValidationError(issues)

    return plan


def _detect_cycles(plan: PlanSpec) -> list[str]:
    """Detect circular dependencies in agent dependencies.

    Returns a list of cycle descriptions (empty = no cycles).
    """
    # Build adjacency list from agent dependencies
    graph: dict[str, list[str]] = {}
    for agent in plan.agents:
        graph[agent.id] = list(agent.dependencies)

    cycles: list[str] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path + [neighbor])
            elif neighbor in rec_stack:
                # Found a cycle
                cycle_start = path.index(neighbor) if neighbor in path else 0
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(" -> ".join(cycle))

        rec_stack.discard(node)

    for agent_id in graph:
        if agent_id not in visited:
            dfs(agent_id, [agent_id])

    return cycles