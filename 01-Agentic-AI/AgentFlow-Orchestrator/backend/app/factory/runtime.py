"""Agent Runtime — executes a single agent with context and limits.

Matches instruction.md section 14 (Agent Runtime).

The runtime wraps BaseAgent.run() with:
- Timeout enforcement
- Event emission
- State persistence (to execution state)
- Error handling
"""

import asyncio
import logging
import time
from typing import Any

from app.factory.base_agent import BaseAgent
from app.factory.context import AgentContext, AgentResult
from app.models.agent import AgentSpec

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Runtime that executes a single agent.

    Usage:
        runtime = AgentRuntime(agent_spec)
        result = await runtime.execute(context)
    """

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self._agent = BaseAgent(spec)

    async def execute(self, context: AgentContext) -> AgentResult:
        """Execute the agent with timeout enforcement.

        Args:
            context: The execution context (intent, inputs, memory).

        Returns:
            AgentResult with status, output, and metrics.
        """
        logger.info(f"Runtime starting agent '{self.spec.id}' (timeout={self.spec.timeout_seconds}s)")

        start_time = time.time()

        try:
            # Enforce timeout via asyncio
            result = await asyncio.wait_for(
                self._agent.run(context),
                timeout=self.spec.timeout_seconds,
            )

            elapsed = time.time() - start_time
            logger.info(
                f"Agent '{self.spec.id}' finished: status={result.status}, "
                f"tool_calls={result.tool_calls}, iterations={result.iterations}, "
                f"duration={elapsed:.1f}s"
            )
            return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(f"Agent '{self.spec.id}' timed out after {elapsed:.1f}s")
            return AgentResult(
                agent_id=self.spec.id,
                status="timed_out",
                error=f"Agent timed out after {self.spec.timeout_seconds}s",
                duration_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Agent '{self.spec.id}' runtime error: {e}", exc_info=True)
            return AgentResult(
                agent_id=self.spec.id,
                status="failed",
                error=str(e),
                duration_seconds=elapsed,
            )


def create_runtime(spec: AgentSpec) -> AgentRuntime:
    """Create an AgentRuntime from an AgentSpec."""
    return AgentRuntime(spec)