"""Pydantic schemas for agents.

AgentSpec defines the specification for a dynamically created agent.
Matches instruction.md section 8 (AgentSpec).
"""

from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    """Specification for a single agent in a plan."""

    id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Human-readable agent name")
    description: str = Field("", description="What this agent does")
    goal: str = Field(..., description="The agent's primary goal")

    model: str = Field("", description="LLM model to use (empty = use default)")
    system_prompt: str = Field("", description="System prompt for the agent")

    tools: list[str] = Field(default_factory=list, description="Tool IDs this agent can use")
    skills: list[str] = Field(default_factory=list, description="Skill IDs this agent can use")
    memory_scopes: list[str] = Field(default_factory=list, description="Memory scopes: working, long_term, skill")

    input_schema: dict = Field(default_factory=dict, description="Expected input schema")
    output_schema: dict = Field(default_factory=dict, description="Expected output schema")

    dependencies: list[str] = Field(default_factory=list, description="Agent IDs this agent depends on")

    max_iterations: int = Field(5, ge=1, le=50, description="Max LLM interaction iterations")
    max_tool_calls: int = Field(20, ge=1, le=200, description="Max tool calls per agent")
    timeout_seconds: int = Field(300, ge=10, le=3600, description="Agent timeout in seconds")

    requires_human_approval: bool = Field(False, description="Whether this agent needs human approval before running")