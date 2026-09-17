"""Evaluation Engine — assesses whether a workflow achieved the user's objective.

Matches instruction.md section 23 (Evaluation Engine).

Evaluator input:
- Original Intent
- Plan
- Agent Outputs
- Tool Results
- Final Output
- Evaluation Criteria

Returns an EvaluationResult with:
- success: bool (overall pass/fail)
- score: float (0.0 to 1.0)
- criteria: dict[str, float] (per-criterion scores)
- issues: list[str] (problems found)
- recommendations: list[str] (suggestions for improvement)

The evaluator uses a combination of:
1. Structural checks (did agents produce output? did tools succeed?)
2. Criteria-based scoring (completeness, accuracy, format, relevance)
3. LLM-based assessment (optional — uses the LLM to judge output quality)

For MVP, the evaluator uses rule-based scoring. LLM-based evaluation
can be enabled by providing a model.
"""

import json
import logging
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from app.llm.config import get_model
from app.models.evaluation import EvaluationResult
from app.models.plan_schema import EvaluationSpec, PlanSpec
from app.orchestrator.state import ExecutionState

logger = logging.getLogger(__name__)


class EvaluationError(Exception):
    """Raised when evaluation fails."""


# --- LLM-facing output schema ---

class LLMEvaluationOutput(BaseModel):
    """Structured output for LLM-based evaluation."""

    score: float = Field(..., ge=0.0, le=1.0, description="Overall score")
    criteria: dict[str, float] = Field(default_factory=dict, description="Per-criterion scores")
    issues: list[str] = Field(default_factory=list, description="Issues found")
    recommendations: list[str] = Field(default_factory=list, description="Recommendations")


EVALUATOR_SYSTEM_PROMPT = """You are an Evaluation Agent for an Agentic AI Workflow Platform.

Your job: evaluate whether a workflow achieved the user's objective.

You will receive:
- The user's original intent
- The plan's objective
- The final output from the workflow's agents
- The evaluation criteria

Score each criterion from 0.0 to 1.0 and provide an overall score.
Identify issues and recommendations for improvement.

Return ONLY a JSON object matching the schema. Do not include any text outside the JSON."""


class EvaluationEngine:
    """Evaluates completed workflow executions.

    Usage:
        engine = EvaluationEngine()
        result = await engine.evaluate(plan, state, intent="Analyze sales data")
    """

    def __init__(self, use_llm: bool = False, model_name: str | None = None) -> None:
        """Initialize the evaluation engine.

        Args:
            use_llm: If True, use LLM-based evaluation. If False, use rule-based only.
            model_name: LLM model to use (if use_llm=True).
        """
        self._use_llm = use_llm
        self._model_name = model_name

    async def evaluate(
        self,
        plan: PlanSpec,
        state: ExecutionState,
        intent: str = "",
    ) -> EvaluationResult:
        """Evaluate a completed workflow execution.

        Args:
            plan: The plan that was executed.
            state: The final execution state (with outputs, failed nodes, etc.).
            intent: The original user intent.

        Returns:
            EvaluationResult with score, criteria, issues, and recommendations.
        """
        await self._emit_event(state.execution_id, "EVALUATION_STARTED", data={
            "intent": intent[:200],
            "plan_objective": plan.objective[:200],
        })

        try:
            # Step 1: Structural checks (rule-based)
            structural = self._structural_evaluation(plan, state)

            # Step 2: Criteria-based scoring
            criteria_scores = self._score_criteria(plan.evaluation, state, structural)

            # Step 3: LLM-based evaluation (optional)
            if self._use_llm and state.status == "completed":
                llm_result = await self._llm_evaluate(plan, state, intent)
                if llm_result:
                    # Merge LLM scores with structural scores (LLM takes precedence)
                    criteria_scores.update(llm_result.criteria)
                    issues = structural["issues"] + llm_result.issues
                    recommendations = llm_result.recommendations
                else:
                    issues = structural["issues"]
                    recommendations = structural["recommendations"]
            else:
                issues = structural["issues"]
                recommendations = structural["recommendations"]

            # Calculate overall score
            if criteria_scores:
                overall_score = sum(criteria_scores.values()) / len(criteria_scores)
            else:
                overall_score = 0.0

            # Determine success
            threshold = plan.evaluation.threshold
            success = state.status == "completed" and overall_score >= threshold

            result = EvaluationResult(
                success=success,
                score=round(overall_score, 4),
                criteria={k: round(v, 4) for k, v in criteria_scores.items()},
                issues=issues,
                recommendations=recommendations,
            )

            await self._emit_event(state.execution_id, "EVALUATION_COMPLETED", data={
                "success": result.success,
                "score": result.score,
                "threshold": threshold,
                "criteria": result.criteria,
            })

            logger.info(
                f"Evaluation for execution {state.execution_id}: "
                f"score={result.score:.2f}, success={result.success}, "
                f"threshold={threshold}"
            )

            return result

        except Exception as e:
            logger.error(f"Evaluation failed: {e}", exc_info=True)
            await self._emit_event(state.execution_id, "EVALUATION_COMPLETED", data={
                "success": False,
                "error": str(e),
            })
            # Return a minimal failure result
            return EvaluationResult(
                success=False,
                score=0.0,
                issues=[f"Evaluation error: {e}"],
                recommendations=["Check execution logs for details"],
            )

    def _structural_evaluation(self, plan: PlanSpec, state: ExecutionState) -> dict[str, Any]:
        """Perform rule-based structural checks on the execution.

        Returns:
            Dict with 'issues', 'agent_outputs_count', 'failed_agents',
            'tool_calls', 'has_output'.
        """
        issues: list[str] = []
        total_agents = len(plan.agents)
        completed_agents = len(state.completed_nodes)
        failed_agents = len(state.failed_nodes)

        # Check if all agents completed
        if failed_agents > 0:
            issues.append(f"{failed_agents} agent(s) failed: {state.failed_nodes}")

        if completed_agents < total_agents:
            issues.append(
                f"Only {completed_agents}/{total_agents} agents completed"
            )

        # Check if any output was produced
        has_output = len(state.outputs) > 0
        if not has_output and state.status == "completed":
            issues.append("No output produced despite completed status")

        # Check for tool call failures
        tool_failures = 0
        for agent_id, output in state.outputs.items():
            # Tool results are stored in the agent context, not directly in state.outputs
            # We check if the output has meaningful content
            if not output:
                issues.append(f"Agent '{agent_id}' produced empty output")

        return {
            "issues": issues,
            "recommendations": [],
            "total_agents": total_agents,
            "completed_agents": completed_agents,
            "failed_agents": failed_agents,
            "has_output": has_output,
            "tool_calls": state.total_tool_calls,
        }

    def _score_criteria(
        self,
        eval_spec: EvaluationSpec,
        state: ExecutionState,
        structural: dict[str, Any],
    ) -> dict[str, float]:
        """Score each evaluation criterion using rule-based heuristics.

        Supported criteria:
        - completeness: did all agents complete and produce output?
        - accuracy: did the execution succeed without errors?
        - format: did agents produce non-empty output?
        - relevance: was the objective addressed (heuristic: output exists)?

        Unknown criteria get a default score based on overall success.
        """
        scores: dict[str, float] = {}

        total_agents = structural["total_agents"]
        completed_agents = structural["completed_agents"]
        has_output = structural["has_output"]

        # LLM-generated plans often omit evaluation.criteria — fall back to
        # sensible defaults instead of scoring nothing (which always fails).
        criteria = eval_spec.criteria or ["completeness", "accuracy"]

        for criterion in criteria:
            criterion_lower = criterion.lower()

            if criterion_lower == "completeness":
                # Score based on how many agents completed
                if total_agents > 0:
                    scores["completeness"] = completed_agents / total_agents
                else:
                    scores["completeness"] = 0.0

            elif criterion_lower == "accuracy":
                # Score based on execution success (no failed agents)
                if state.status == "completed" and structural["failed_agents"] == 0:
                    scores["accuracy"] = 1.0
                elif state.status == "completed":
                    scores["accuracy"] = 0.5
                else:
                    scores["accuracy"] = 0.0

            elif criterion_lower == "format":
                # Score based on whether outputs are non-empty
                non_empty = sum(1 for v in state.outputs.values() if v)
                total_outputs = len(state.outputs)
                if total_outputs > 0:
                    scores["format"] = non_empty / total_outputs
                else:
                    scores["format"] = 0.0

            elif criterion_lower == "relevance":
                # Heuristic: if output exists, it's likely relevant
                scores["relevance"] = 1.0 if has_output else 0.0

            else:
                # Unknown criterion — default based on overall success
                scores[criterion] = 1.0 if state.status == "completed" else 0.0

        return scores

    async def _llm_evaluate(
        self,
        plan: PlanSpec,
        state: ExecutionState,
        intent: str,
    ) -> EvaluationResult | None:
        """Use an LLM to evaluate the workflow output quality.

        Returns None if the LLM call fails.
        """
        try:
            model = get_model(self._model_name)
            agent = LlmAgent(
                name="evaluator_agent",
                description="Evaluates workflow output quality",
                instruction=EVALUATOR_SYSTEM_PROMPT,
                model=model,
                output_schema=LLMEvaluationOutput,
                output_key="eval_output",
            )

            session_service = InMemorySessionService()
            runner = Runner(
                agent=agent,
                app_name="agentos_evaluator",
                session_service=session_service,
            )
            session_id = f"eval_{uuid.uuid4().hex[:8]}"

            await session_service.create_session(
                app_name="agentos_evaluator",
                user_id="evaluator",
                session_id=session_id,
            )

            # Build evaluation prompt
            prompt = self._build_eval_prompt(plan, state, intent)
            user_content = types.Content(
                role="user",
                parts=[types.Part(text=prompt)],
            )

            final_text: str | None = None
            async for event in runner.run_async(
                user_id="evaluator",
                session_id=session_id,
                new_message=user_content,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    final_text = event.content.parts[0].text.strip()

            try:
                await session_service.delete_session(
                    app_name="agentos_evaluator",
                    user_id="evaluator",
                    session_id=session_id,
                )
            except Exception:
                pass

            if not final_text:
                return None

            # Parse JSON
            import json as json_module

            try:
                data = json_module.loads(final_text)
            except json_module.JSONDecodeError:
                # Try to extract from markdown
                if "```json" in final_text:
                    start = final_text.index("```json") + 7
                    end = final_text.index("```", start)
                    data = json_module.loads(final_text[start:end].strip())
                else:
                    return None

            llm_output = LLMEvaluationOutput(**data)
            return EvaluationResult(
                success=llm_output.score >= plan.evaluation.threshold,
                score=llm_output.score,
                criteria=llm_output.criteria,
                issues=llm_output.issues,
                recommendations=llm_output.recommendations,
            )

        except Exception as e:
            logger.warning(f"LLM evaluation failed (falling back to rule-based): {e}")
            return None

    def _build_eval_prompt(self, plan: PlanSpec, state: ExecutionState, intent: str) -> str:
        """Build the prompt for LLM-based evaluation."""
        parts = [
            f"User Intent: {intent}",
            f"Plan Objective: {plan.objective}",
            f"Execution Status: {state.status}",
            f"Completed Agents: {state.completed_nodes}",
            f"Failed Agents: {state.failed_nodes}",
            f"Total Tool Calls: {state.total_tool_calls}",
            f"Evaluation Criteria: {plan.evaluation.criteria}",
            f"Threshold: {plan.evaluation.threshold}",
            "\nAgent Outputs:",
        ]

        for agent_id, output in state.outputs.items():
            output_str = json.dumps(output, default=str)[:500]
            parts.append(f"  {agent_id}: {output_str}")

        parts.append("\nEvaluate this workflow. Score each criterion from 0.0 to 1.0.")
        parts.append("Return ONLY the JSON object matching the schema.")
        return "\n".join(parts)

    async def _emit_event(self, execution_id: str, event_type: str, data: dict) -> None:
        """Emit an evaluation event."""
        try:
            from app.orchestrator.events import get_event_manager
            event_manager = get_event_manager()
            await event_manager.emit(
                execution_id=execution_id,
                event_type=event_type,
                data=data,
            )
        except Exception:
            pass  # Best-effort event emission


# --- Singleton ---

_engine: EvaluationEngine | None = None


def get_evaluation_engine() -> EvaluationEngine:
    """Get the singleton EvaluationEngine instance.

    Defaults to rule-based evaluation (no LLM) for speed and reliability.
    Enable LLM evaluation by calling with use_llm=True.
    """
    global _engine
    if _engine is None:
        _engine = EvaluationEngine(use_llm=False)
    return _engine