"""Agent context — passed to agents during execution.

Contains working memory, tool results, dependency outputs, and shared state.
Matches instruction.md section 14 (Agent Runtime) and section 18 (Memory).
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    """Context passed to an agent during execution.

    Contains:
    - task_id: The parent task ID
    - execution_id: The execution instance ID
    - intent: The original user intent
    - inputs: Data from upstream agents (dependency outputs)
    - working_memory: Shared working memory for this execution
    - tool_results: Results of tool calls made by this agent
    - metadata: Extra metadata
    """

    task_id: str = ""
    execution_id: str = ""
    intent: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict, description="Outputs from dependency agents, keyed by agent ID")
    working_memory: dict[str, Any] = Field(default_factory=dict, description="Shared working memory for this execution")
    tool_results: list[dict[str, Any]] = Field(default_factory=list, description="Results of tool calls made by this agent")
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_tool_result(self, tool_id: str, params: dict, result: dict) -> None:
        """Record a tool execution result."""
        self.tool_results.append({
            "tool_id": tool_id,
            "params": params,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def set_memory(self, key: str, value: Any) -> None:
        """Set a value in working memory."""
        self.working_memory[key] = value

    def get_memory(self, key: str, default: Any = None) -> Any:
        """Get a value from working memory."""
        return self.working_memory.get(key, default)


class AgentResult(BaseModel):
    """Result of an agent execution.

    Matches instruction.md section 14 (Agent Runtime).
    """

    agent_id: str = ""
    status: str = Field("completed", description="completed, failed, timed_out")
    output: dict[str, Any] = Field(default_factory=dict, description="Agent output data")
    error: str | None = Field(None, description="Error message if failed")
    tool_calls: int = Field(0, description="Number of tool calls made")
    iterations: int = Field(0, description="Number of LLM iterations")
    duration_seconds: float = Field(0.0, description="Execution duration")
    events: list[dict[str, Any]] = Field(default_factory=list, description="Events emitted by this agent")

    @property
    def success(self) -> bool:
        return self.status == "completed"