"""Policy Engine — evaluates permissions and determines if approval is needed.

Matches instruction.md section 20 (Tool Security) and section 21 (Policy Engine).

Permission levels (from instruction.md §20):
- READ: file reading, calculations
- WRITE: file writing, code execution
- EXTERNAL_ACTION: HTTP requests, web search, emails
- DESTRUCTIVE: file deletion, irreversible operations

The Policy Engine:
1. Checks if an agent's tools require approval
2. Checks if the agent itself requires human approval
3. Returns a PolicyDecision indicating whether to proceed, pause for approval, or deny
"""

import logging
from typing import Any

from app.models.agent import AgentSpec
from app.tools.registry import get_registry

logger = logging.getLogger(__name__)

# Permission level hierarchy (higher = more dangerous)
PERMISSION_LEVELS = {
    "READ": 0,
    "WRITE": 1,
    "EXTERNAL_ACTION": 2,
    "DESTRUCTIVE": 3,
}

# Permission levels that require human approval
APPROVAL_REQUIRED_LEVELS = {"EXTERNAL_ACTION", "DESTRUCTIVE"}


class PolicyDecision:
    """Result of a policy evaluation.

    Attributes:
        allowed: Whether the action is allowed without approval.
        requires_approval: Whether human approval is needed before proceeding.
        reason: Human-readable explanation.
        approval_type: Type of approval needed (if any): "tool", "agent", "destructive_action".
        approval_context: Context data for the approval request.
    """

    def __init__(
        self,
        allowed: bool = True,
        requires_approval: bool = False,
        reason: str = "",
        approval_type: str = "",
        approval_context: dict[str, Any] | None = None,
    ) -> None:
        self.allowed = allowed
        self.requires_approval = requires_approval
        self.reason = reason
        self.approval_type = approval_type
        self.approval_context = approval_context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "approval_type": self.approval_type,
            "approval_context": self.approval_context,
        }


class PolicyEngine:
    """Evaluates whether an agent execution requires human approval.

    Usage:
        engine = PolicyEngine()
        decision = engine.evaluate(agent_spec)
        if decision.requires_approval:
            # Pause execution and create approval request
    """

    def __init__(self) -> None:
        self._registry = get_registry()

    def evaluate(self, agent_spec: AgentSpec) -> PolicyDecision:
        """Evaluate whether an agent requires human approval before execution.

        Checks:
        1. If agent_spec.requires_human_approval is True → always require approval
        2. If any of the agent's tools have EXTERNAL_ACTION or DESTRUCTIVE permission → require approval
        3. Otherwise → allow without approval

        Args:
            agent_spec: The agent to evaluate.

        Returns:
            PolicyDecision indicating whether to proceed or pause.
        """
        # Check 1: Agent explicitly requires human approval
        if agent_spec.requires_human_approval:
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                reason=f"Agent '{agent_spec.id}' explicitly requires human approval",
                approval_type="agent",
                approval_context={
                    "agent_id": agent_spec.id,
                    "agent_name": agent_spec.name,
                    "agent_goal": agent_spec.goal,
                    "tools": agent_spec.tools,
                },
            )

        # Check 2: Any tool requires approval
        approval_tools: list[dict[str, Any]] = []
        max_permission_level = "READ"

        for tool_id in agent_spec.tools:
            try:
                tool = self._registry.get(tool_id)
                perm_level = tool.permission_level

                # Track the highest permission level
                if PERMISSION_LEVELS.get(perm_level, 0) > PERMISSION_LEVELS.get(max_permission_level, 0):
                    max_permission_level = perm_level

                # Check if this tool requires approval
                if perm_level in APPROVAL_REQUIRED_LEVELS:
                    approval_tools.append({
                        "tool_id": tool_id,
                        "tool_name": tool.name,
                        "permission_level": perm_level,
                    })
            except Exception:
                # Tool not found — skip (factory will catch this separately)
                pass

        if approval_tools:
            reason = (
                f"Agent '{agent_spec.id}' uses tools requiring approval: "
                f"{[t['tool_id'] for t in approval_tools]}"
            )
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                reason=reason,
                approval_type="tool",
                approval_context={
                    "agent_id": agent_spec.id,
                    "agent_name": agent_spec.name,
                    "agent_goal": agent_spec.goal,
                    "tools_requiring_approval": approval_tools,
                    "max_permission_level": max_permission_level,
                },
            )

        # Check 3: No approval needed
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason=f"Agent '{agent_spec.id}' does not require approval",
        )


# --- Singleton ---

_policy_engine: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    """Get the singleton PolicyEngine instance."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine