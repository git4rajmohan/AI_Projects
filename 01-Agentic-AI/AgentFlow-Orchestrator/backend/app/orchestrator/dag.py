"""DAG Engine — builds and resolves agent dependency graphs.

Matches instruction.md section 15 (Orchestration Engine).

Supports:
- Sequential: A → B → C
- Parallel: A → {B, C, D} (independent agents run concurrently)
- Merge: {B, C, D} → E (E waits for all dependencies)
- Conditional: A → IF condition → B (true) / C (false)
- Retry: A fails → retry (configurable max retries)

The DAG engine performs topological sorting to determine execution order
and identifies which agents can run in parallel (same topological level).
"""

import logging
from collections import defaultdict, deque
from typing import Any

from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec

logger = logging.getLogger(__name__)


class DAGError(Exception):
    """Raised when the DAG is invalid (cycles, missing deps, etc.)."""


class DAGNode:
    """A node in the execution DAG."""

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self.id = spec.id
        self.dependencies: set[str] = set(spec.dependencies)
        self.dependents: set[str] = set()  # agents that depend on this one
        self.level: int = 0  # topological level (0 = no dependencies)

    def __repr__(self) -> str:
        return f"DAGNode(id={self.id}, deps={self.dependencies}, level={self.level})"


class ExecutionDAG:
    """A directed acyclic graph of agent execution order.

    Built from a PlanSpec, this determines:
    - Which agents can run in parallel
    - Which agents must wait for others
    - The topological execution order
    """

    def __init__(self, plan: PlanSpec) -> None:
        self.plan = plan
        self.nodes: dict[str, DAGNode] = {}
        self._build()

    def _build(self) -> None:
        """Build the DAG from the plan's agent specs."""
        # Create nodes
        for agent_spec in self.plan.agents:
            if agent_spec.id in self.nodes:
                raise DAGError(f"Duplicate agent ID: {agent_spec.id}")
            self.nodes[agent_spec.id] = DAGNode(agent_spec)

        # Validate dependencies reference existing agents
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                if dep_id not in self.nodes:
                    raise DAGError(
                        f"Agent '{node.id}' depends on unknown agent '{dep_id}'"
                    )

        # Build reverse edges (dependents)
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                self.nodes[dep_id].dependents.add(node.id)

        # Compute topological levels
        self._compute_levels()

        # Check for cycles
        if self._has_cycle():
            raise DAGError("Circular dependency detected in plan")

    def _compute_levels(self) -> None:
        """Compute the topological level for each node.

        Level 0 = no dependencies
        Level N = max(deps' levels) + 1

        Agents at the same level can run in parallel.
        """
        # Kahn's algorithm for topological leveling
        in_degree: dict[str, int] = {}
        queue: deque[str] = deque()

        for node_id, node in self.nodes.items():
            in_degree[node_id] = len(node.dependencies)
            if in_degree[node_id] == 0:
                queue.append(node_id)
                node.level = 0

        processed = 0
        while queue:
            current_id = queue.popleft()
            current = self.nodes[current_id]
            processed += 1

            for dependent_id in current.dependents:
                dependent = self.nodes[dependent_id]
                # Level = max of all dependency levels + 1
                dep_level = current.level + 1
                if dep_level > dependent.level:
                    dependent.level = dep_level

                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if processed != len(self.nodes):
            # This means there's a cycle — will be caught by _has_cycle
            pass

    def _has_cycle(self) -> bool:
        """Check if the DAG has a cycle using DFS."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in self.nodes}

        def dfs(node_id: str) -> bool:
            color[node_id] = GRAY
            for dep_id in self.nodes[node_id].dependencies:
                if color[dep_id] == GRAY:
                    return True  # Back edge → cycle
                if color[dep_id] == WHITE and dfs(dep_id):
                    return True
            color[node_id] = BLACK
            return False

        return any(color[nid] == WHITE and dfs(nid) for nid in self.nodes)

    def get_execution_levels(self) -> list[list[str]]:
        """Return agents grouped by topological level.

        Each level is a list of agent IDs that can run in parallel.
        Levels must be executed in order (level 0 first, then 1, etc.).

        Returns:
            List of lists, e.g. [["a"], ["b", "c"], ["d"]]
        """
        if not self.nodes:
            return []

        max_level = max(n.level for n in self.nodes.values())
        levels: list[list[str]] = [[] for _ in range(max_level + 1)]

        for node_id, node in self.nodes.items():
            levels[node.level].append(node_id)

        return levels

    def get_ready_agents(self, completed: set[str]) -> list[str]:
        """Get agent IDs whose dependencies are all completed.

        Args:
            completed: Set of agent IDs that have completed successfully.

        Returns:
            List of agent IDs ready to execute (deps satisfied, not yet completed).
        """
        ready: list[str] = []
        for node_id, node in self.nodes.items():
            if node_id in completed:
                continue
            if node.dependencies.issubset(completed):
                ready.append(node_id)
        return ready

    def get_agent(self, agent_id: str) -> AgentSpec:
        """Get the AgentSpec for a given agent ID."""
        if agent_id not in self.nodes:
            raise DAGError(f"Unknown agent ID: {agent_id}")
        return self.nodes[agent_id].spec

    def get_dependencies(self, agent_id: str) -> set[str]:
        """Get the set of dependency agent IDs for a given agent."""
        if agent_id not in self.nodes:
            raise DAGError(f"Unknown agent ID: {agent_id}")
        return self.nodes[agent_id].dependencies

    @property
    def agent_ids(self) -> list[str]:
        """All agent IDs in the DAG."""
        return list(self.nodes.keys())

    @property
    def is_empty(self) -> bool:
        """True if the DAG has no agents."""
        return len(self.nodes) == 0