"""Orchestrator — executes multi-agent workflows as a DAG.

Matches instruction.md section 15 (Orchestration Engine).

The orchestrator:
1. Builds a DAG from the plan's agent specs
2. Executes agents level-by-level (topological order)
3. Agents at the same level run in parallel (asyncio.gather)
4. Failed agents are retried up to max_retries
5. State is persisted after each agent completes
6. Events are emitted for every step
7. Execution can be cancelled mid-flight

Supports:
- Sequential: A → B → C
- Parallel: {B, C, D} run concurrently
- Merge: E waits for {B, C, D} to complete
- Retry: failed agent retries (configurable)
- Cancel: stop execution gracefully
"""

import asyncio
import logging
import time
from typing import Any

from app.core.config import settings
from app.evaluation.engine import EvaluationResult, get_evaluation_engine
from app.evaluation.replanner import ReplanError, get_replanner
from app.factory.agent_factory import AgentFactory, get_factory
from app.factory.context import AgentContext, AgentResult
from app.models.plan_schema import PlanSpec
from app.orchestrator.dag import DAGError, ExecutionDAG
from app.orchestrator.events import get_event_manager
from app.orchestrator.state import ExecutionState, get_state_manager
from app.policy.approval import get_approval_manager
from app.policy.engine import get_policy_engine

logger = logging.getLogger(__name__)


class OrchestrationError(Exception):
    """Raised when orchestration fails."""


class Orchestrator:
    """Executes a plan as a multi-agent DAG workflow.

    Usage:
        orchestrator = Orchestrator()
        result = await orchestrator.execute(plan, task_id="...", execution_id="...")
    """

    def __init__(self, max_retries: int | None = None) -> None:
        self._factory = get_factory()
        self._state_manager = get_state_manager()
        self._event_manager = get_event_manager()
        self._max_retries = max_retries if max_retries is not None else settings.max_replans
        self._policy_engine = get_policy_engine()
        self._approval_manager = get_approval_manager()
        # Track active executions for cancellation
        self._active_executions: dict[str, asyncio.Event] = {}

    async def execute(
        self,
        plan: PlanSpec,
        task_id: str,
        execution_id: str,
        intent: str = "",
    ) -> ExecutionState:
        """Execute a plan as a multi-agent workflow.

        Args:
            plan: The PlanSpec to execute.
            task_id: The parent task ID.
            execution_id: The execution instance ID.
            intent: The original user intent.

        Returns:
            The final ExecutionState.
        """
        start_time = time.time()

        # Build DAG
        try:
            dag = ExecutionDAG(plan)
        except DAGError as e:
            logger.error(f"DAG construction failed: {e}")
            state = await self._state_manager.load_state(execution_id)
            if state:
                state.mark_failed(str(e))
                await self._state_manager.save_state(state)
            raise OrchestrationError(f"DAG construction failed: {e}")

        if dag.is_empty:
            raise OrchestrationError("Plan has no agents to execute")

        # Load state
        state = await self._state_manager.load_state(execution_id)
        if state is None:
            raise OrchestrationError(f"Execution {execution_id} not found")

        # Set up cancellation tracking
        cancel_event = asyncio.Event()
        self._active_executions[execution_id] = cancel_event

        # Mark execution as started
        state.mark_started()
        await self._state_manager.save_state(state)
        await self._event_manager.emit(
            execution_id=execution_id,
            event_type="TASK_STARTED",
            data={"task_id": task_id, "plan_id": state.plan_id, "agent_count": len(dag.agent_ids)},
        )

        try:
            # Create agent runtimes
            runtimes = self._factory.create_agents(plan)

            # Execute level by level
            levels = dag.get_execution_levels()
            logger.info(
                f"Orchestrating execution {execution_id}: "
                f"{len(dag.agent_ids)} agents in {len(levels)} levels"
            )

            for level_idx, level_agent_ids in enumerate(levels):
                if cancel_event.is_set():
                    logger.info(f"Execution {execution_id} cancelled at level {level_idx}")
                    state.mark_cancelled()
                    await self._state_manager.save_state(state)
                    await self._event_manager.emit(
                        execution_id=execution_id,
                        event_type="TASK_CANCELLED",
                        data={"level": level_idx},
                    )
                    return state

                logger.info(
                    f"Execution {execution_id} level {level_idx}: "
                    f"running {len(level_agent_ids)} agents: {level_agent_ids}"
                )

                # Run all agents at this level in parallel
                tasks = []
                for agent_id in level_agent_ids:
                    if agent_id in state.completed_nodes:
                        logger.info(f"Agent '{agent_id}' already completed — skipping")
                        continue

                    task = self._execute_agent_with_retry(
                        dag=dag,
                        runtimes=runtimes,
                        agent_id=agent_id,
                        state=state,
                        execution_id=execution_id,
                        intent=intent or plan.objective,
                        cancel_event=cancel_event,
                    )
                    tasks.append(task)

                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Check for failures
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            agent_id = level_agent_ids[i]
                            logger.error(
                                f"Agent '{agent_id}' raised exception: {result}",
                                exc_info=result,
                            )
                            state.mark_failed_node(agent_id)
                            await self._event_manager.emit(
                                execution_id=execution_id,
                                event_type="AGENT_FAILED",
                                agent_id=agent_id,
                                error=str(result),
                            )

                # Save state after each level
                await self._state_manager.save_state(state)

                # Check if any agents failed at this level
                failed_at_level = [aid for aid in level_agent_ids if aid in state.failed_nodes]
                if failed_at_level:
                    logger.error(
                        f"Execution {execution_id} failed at level {level_idx}: "
                        f"agents {failed_at_level} failed"
                    )
                    state.mark_failed(
                        f"Agents failed at level {level_idx}: {failed_at_level}"
                    )
                    await self._state_manager.save_state(state)
                    await self._event_manager.emit(
                        execution_id=execution_id,
                        event_type="TASK_FAILED",
                        error=state.error,
                        data={"failed_agents": failed_at_level, "level": level_idx},
                    )
                    return state

            # All agents completed successfully
            elapsed = time.time() - start_time
            state.mark_completed()
            state.result = {
                "outputs": state.outputs,
                "total_tool_calls": state.total_tool_calls,
                "duration_seconds": elapsed,
            }
            await self._state_manager.save_state(state)
            await self._event_manager.emit(
                execution_id=execution_id,
                event_type="TASK_COMPLETED",
                status="success",
                duration_ms=int(elapsed * 1000),
                data={
                    "completed_agents": state.completed_nodes,
                    "total_tool_calls": state.total_tool_calls,
                },
            )

            logger.info(
                f"Execution {execution_id} completed in {elapsed:.1f}s "
                f"({len(state.completed_nodes)} agents, {state.total_tool_calls} tool calls)"
            )
            return state

        except asyncio.CancelledError:
            logger.info(f"Execution {execution_id} was cancelled")
            state.mark_cancelled()
            await self._state_manager.save_state(state)
            await self._event_manager.emit(
                execution_id=execution_id,
                event_type="TASK_CANCELLED",
            )
            return state
        except Exception as e:
            logger.error(f"Execution {execution_id} failed: {e}", exc_info=True)
            state.mark_failed(str(e))
            await self._state_manager.save_state(state)
            await self._event_manager.emit(
                execution_id=execution_id,
                event_type="TASK_FAILED",
                error=str(e),
            )
            return state
        finally:
            self._active_executions.pop(execution_id, None)

    async def execute_with_evaluation(
        self,
        plan: PlanSpec,
        task_id: str,
        execution_id: str,
        intent: str = "",
        max_replans: int | None = None,
    ) -> tuple[ExecutionState, EvaluationResult]:
        """Execute a plan, evaluate the result, and replan if needed.

        This wraps the basic `execute` method with an evaluation loop:
        1. Execute the plan
        2. Evaluate the result
        3. If evaluation fails and replans remain → replan and retry
        4. If evaluation passes or replans exhausted → return final result

        Args:
            plan: The PlanSpec to execute.
            task_id: The parent task ID.
            execution_id: The execution instance ID.
            intent: The original user intent.
            max_replans: Maximum replan attempts (default: settings.max_replans).

        Returns:
            Tuple of (final ExecutionState, final EvaluationResult).
        """
        max_replans = max_replans if max_replans is not None else settings.max_replans
        eval_engine = get_evaluation_engine()
        replanner = get_replanner()

        current_plan = plan
        current_state: ExecutionState | None = None
        current_eval: EvaluationResult | None = None

        for attempt in range(max_replans + 1):
            # Execute the plan
            current_state = await self.execute(
                plan=current_plan,
                task_id=task_id,
                execution_id=execution_id,
                intent=intent,
            )

            # Evaluate the result
            current_eval = await eval_engine.evaluate(
                plan=current_plan,
                state=current_state,
                intent=intent,
            )

            # Store evaluation result in state
            if current_state.result is None:
                current_state.result = {}
            current_state.result["evaluation"] = current_eval.model_dump()
            await self._state_manager.save_state(current_state)

            # Check if evaluation passed
            if current_eval.success:
                logger.info(
                    f"Execution {execution_id} passed evaluation "
                    f"(score={current_eval.score:.2f}, attempt={attempt + 1})"
                )
                return current_state, current_eval

            # Check if we have replans remaining
            if attempt >= max_replans:
                logger.warning(
                    f"Execution {execution_id} failed evaluation after "
                    f"{max_replans + 1} attempts (final score={current_eval.score:.2f})"
                )
                return current_state, current_eval

            # Replan
            logger.info(
                f"Execution {execution_id} evaluation failed "
                f"(score={current_eval.score:.2f}), replanning (attempt {attempt + 2})"
            )

            try:
                current_plan = await replanner.replan(
                    original_plan=current_plan,
                    eval_result=current_eval,
                    state=current_state,
                    intent=intent,
                    attempt=attempt + 1,
                )
            except ReplanError as e:
                logger.error(f"Replanning failed: {e}")
                return current_state, current_eval

            # Create a new execution for the replanned attempt
            new_state = await self._state_manager.create_execution(
                task_id=task_id,
                plan_id=current_state.plan_id,
            )
            execution_id = new_state.execution_id

        # Should not reach here, but just in case
        return current_state or ExecutionState("", "", ""), current_eval or EvaluationResult(
            success=False, score=0.0, issues=["Unexpected end of replan loop"]
        )

    async def _execute_agent_with_retry(
        self,
        dag: ExecutionDAG,
        runtimes: dict,
        agent_id: str,
        state: ExecutionState,
        execution_id: str,
        intent: str,
        cancel_event: asyncio.Event,
    ) -> AgentResult:
        """Execute a single agent with retry logic.

        Retries up to self._max_retries times on failure.
        """
        agent_spec = dag.get_agent(agent_id)
        runtime = runtimes[agent_id]
        dependencies = dag.get_dependencies(agent_id)

        # Gather dependency outputs for this agent's context
        dependency_outputs = {
            dep_id: state.outputs.get(dep_id, {}) for dep_id in dependencies
        }

        # --- Approval Gate ---
        # Check if this agent requires human approval before execution
        policy_decision = self._policy_engine.evaluate(agent_spec)
        if policy_decision.requires_approval:
            logger.info(
                f"Agent '{agent_id}' requires approval: {policy_decision.reason}"
            )

            # Pause execution
            state.mark_paused()
            await self._state_manager.save_state(state)

            # Create approval request
            approval_id = await self._approval_manager.create_request(
                execution_id=execution_id,
                approval_type=policy_decision.approval_type,
                context=policy_decision.approval_context,
                task_id=state.task_id,
            )

            # Wait for approval (with timeout)
            try:
                decision = await self._approval_manager.wait_for_approval(
                    approval_id,
                    timeout=3600.0,  # 1 hour max wait
                )
            except Exception as e:
                logger.error(f"Approval wait failed for agent '{agent_id}': {e}")
                state.mark_failed_node(agent_id)
                await self._state_manager.save_state(state)
                self._approval_manager.cleanup(approval_id)
                return AgentResult(
                    agent_id=agent_id,
                    status="failed",
                    error=f"Approval wait failed: {e}",
                )

            self._approval_manager.cleanup(approval_id)

            if decision == "rejected":
                logger.info(f"Agent '{agent_id}' was rejected by user")
                state.mark_failed_node(agent_id)
                await self._state_manager.save_state(state)
                return AgentResult(
                    agent_id=agent_id,
                    status="failed",
                    error="Agent execution rejected by user",
                )

            # Approved — resume execution
            logger.info(f"Agent '{agent_id}' approved by user — resuming")
            state.status = "running"
            await self._state_manager.save_state(state)

        # --- End Approval Gate ---

        last_result: AgentResult | None = None

        for attempt in range(self._max_retries + 1):
            if cancel_event.is_set():
                return AgentResult(
                    agent_id=agent_id,
                    status="failed",
                    error="Execution cancelled",
                )

            # Mark agent as started
            state.mark_node_started(agent_id)
            await self._state_manager.save_state(state)

            await self._event_manager.emit(
                execution_id=execution_id,
                event_type="AGENT_STARTED",
                agent_id=agent_id,
                data={"attempt": attempt + 1, "max_retries": self._max_retries},
            )

            logger.info(
                f"Agent '{agent_id}' starting (attempt {attempt + 1}/"
                f"{self._max_retries + 1})"
            )

            # Create context
            context = AgentContext(
                task_id=state.task_id,
                execution_id=execution_id,
                intent=intent,
                inputs=dependency_outputs,
                working_memory=state.outputs.copy(),
            )

            # Execute
            result = await runtime.execute(context)
            last_result = result

            if result.success:
                # Record output
                state.add_output(agent_id, result.output)
                state.total_tool_calls += result.tool_calls
                await self._state_manager.save_state(state)

                await self._event_manager.emit(
                    execution_id=execution_id,
                    event_type="AGENT_COMPLETED",
                    agent_id=agent_id,
                    status="success",
                    duration_ms=int(result.duration_seconds * 1000),
                    data={
                        "tool_calls": result.tool_calls,
                        "iterations": result.iterations,
                        "attempt": attempt + 1,
                    },
                )

                logger.info(
                    f"Agent '{agent_id}' completed successfully "
                    f"(attempt {attempt + 1}, {result.tool_calls} tool calls, "
                    f"{result.duration_seconds:.1f}s)"
                )
                return result

            # Agent failed
            logger.warning(
                f"Agent '{agent_id}' failed (attempt {attempt + 1}): {result.error}"
            )

            await self._event_manager.emit(
                execution_id=execution_id,
                event_type="AGENT_FAILED",
                agent_id=agent_id,
                status="failure",
                error=result.error,
                data={"attempt": attempt + 1, "will_retry": attempt < self._max_retries},
            )

            if attempt < self._max_retries:
                logger.info(f"Retrying agent '{agent_id}' (attempt {attempt + 2})")
                await asyncio.sleep(1.0 * (attempt + 1))  # Simple backoff
            else:
                logger.error(
                    f"Agent '{agent_id}' exhausted retries ({self._max_retries + 1} attempts)"
                )

        # All retries exhausted
        state.mark_failed_node(agent_id)
        await self._state_manager.save_state(state)
        return last_result or AgentResult(
            agent_id=agent_id,
            status="failed",
            error="Unknown failure",
        )

    def cancel(self, execution_id: str) -> bool:
        """Request cancellation of a running execution.

        Args:
            execution_id: The execution to cancel.

        Returns:
            True if the execution was found and cancellation was requested.
        """
        cancel_event = self._active_executions.get(execution_id)
        if cancel_event is None:
            return False
        cancel_event.set()
        logger.info(f"Cancellation requested for execution {execution_id}")
        return True


# --- Singleton ---

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """Get the singleton Orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator