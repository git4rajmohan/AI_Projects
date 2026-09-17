"""Replanner — generates a revised plan when evaluation fails.

Matches instruction.md section 24 (Replanning).

Flow:
  Execution → Evaluation → Failure → Replanner → Modified Plan → Execution

The replanner:
1. Takes the original plan, evaluation result, and execution state
2. Analyzes what went wrong (failed agents, low scores, issues)
3. Generates a revised plan via the LLM Planner
4. The revised plan addresses the identified issues

Constraints:
- MAX_REPLANS = settings.max_replans (default: 2)
- Never allow infinite planning loops
"""

import logging
from typing import Any

from app.models.evaluation import EvaluationResult
from app.models.plan_schema import PlanSpec
from app.orchestrator.state import ExecutionState
from app.planner.planner import get_planner

logger = logging.getLogger(__name__)


class ReplanError(Exception):
    """Raised when replanning fails."""


class Replanner:
    """Generates revised plans when evaluation fails.

    Usage:
        replanner = Replanner()
        new_plan = await replanner.replan(
            original_plan=plan,
            eval_result=evaluation,
            state=state,
            intent="Analyze sales data",
            attempt=1,
        )
    """

    def __init__(self) -> None:
        self._planner = get_planner()

    async def replan(
        self,
        original_plan: PlanSpec,
        eval_result: EvaluationResult,
        state: ExecutionState,
        intent: str,
        attempt: int = 1,
    ) -> PlanSpec:
        """Generate a revised plan based on evaluation feedback.

        Args:
            original_plan: The plan that was executed.
            eval_result: The evaluation result (with issues and recommendations).
            state: The execution state (with failed agents, outputs, etc.).
            intent: The original user intent.
            attempt: The replan attempt number (1 = first replan).

        Returns:
            A new PlanSpec that addresses the identified issues.

        Raises:
            ReplanError: If replanning fails.
        """
        logger.info(
            f"Replanning for task {original_plan.task_id} "
            f"(attempt {attempt}, eval_score={eval_result.score:.2f})"
        )

        # Build a replan prompt that includes the failure context
        replan_intent = self._build_replan_intent(
            original_plan, eval_result, state, intent, attempt
        )

        try:
            # Use the LLM Planner to generate a new plan with the enhanced context
            new_plan = await self._planner.create_plan(
                task_id=original_plan.task_id,
                intent_text=replan_intent,
            )

            logger.info(
                f"Replan {attempt} generated: {len(new_plan.agents)} agents, "
                f"objective: {new_plan.objective[:80]}..."
            )

            return new_plan

        except Exception as e:
            logger.error(f"Replanning failed: {e}", exc_info=True)
            raise ReplanError(f"Replanning failed: {e}")

    def _build_replan_intent(
        self,
        original_plan: PlanSpec,
        eval_result: EvaluationResult,
        state: ExecutionState,
        intent: str,
        attempt: int,
    ) -> str:
        """Build an enhanced intent string that includes failure context.

        This gives the planner information about what went wrong so it can
        generate a better plan.
        """
        parts = [
            f"Original intent: {intent}",
            f"Previous plan objective: {original_plan.objective}",
            f"Replan attempt: {attempt}",
            "",
            "Previous execution results:",
            f"  Status: {state.status}",
            f"  Completed agents: {state.completed_nodes}",
            f"  Failed agents: {state.failed_nodes}",
            f"  Total tool calls: {state.total_tool_calls}",
            "",
            f"Evaluation score: {eval_result.score:.2f}",
            f"Evaluation criteria: {eval_result.criteria}",
            "",
            "Issues identified:",
        ]

        for issue in eval_result.issues:
            parts.append(f"  - {issue}")

        if eval_result.recommendations:
            parts.append("")
            parts.append("Recommendations:")
            for rec in eval_result.recommendations:
                parts.append(f"  - {rec}")

        # Include agent outputs for context
        if state.outputs:
            parts.append("")
            parts.append("Previous agent outputs (for reference):")
            for agent_id, output in state.outputs.items():
                import json
                output_str = json.dumps(output, default=str)[:300]
                parts.append(f"  {agent_id}: {output_str}")

        parts.append("")
        parts.append(
            "Based on the above, create a REVISED plan that addresses the issues. "
            "The new plan should fix the identified problems and achieve the original objective."
        )

        return "\n".join(parts)


# --- Singleton ---

_replanner: Replanner | None = None


def get_replanner() -> Replanner:
    """Get the singleton Replanner instance."""
    global _replanner
    if _replanner is None:
        _replanner = Replanner()
    return _replanner