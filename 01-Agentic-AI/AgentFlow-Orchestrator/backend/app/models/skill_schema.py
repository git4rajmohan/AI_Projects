"""Pydantic schemas for skills.

SkillSpec defines a reusable workflow that can be saved, versioned, and reused.
Matches instruction.md section 8 (SkillSpec).
"""

from pydantic import BaseModel, Field


class SkillSpec(BaseModel):
    """Specification for a reusable skill."""

    id: str = Field(..., description="Unique skill identifier")
    name: str = Field(..., description="Human-readable skill name")
    description: str = Field(..., description="What this skill does")
    version: str = Field("1.0.0", description="Semantic version")

    inputs: dict = Field(default_factory=dict, description="Input schema")
    outputs: dict = Field(default_factory=dict, description="Output schema")

    agents: list[str] = Field(default_factory=list, description="Agent IDs used by this skill")
    tools: list[str] = Field(default_factory=list, description="Tool IDs used by this skill")

    workflow: dict = Field(default_factory=dict, description="Workflow definition (DAG structure)")

    evaluation: dict = Field(default_factory=dict, description="Evaluation criteria")
    permissions: dict = Field(default_factory=dict, description="Permission requirements")

    author: str | None = Field(None, description="Skill author")
    tags: list[str] = Field(default_factory=list, description="Tags for discovery")

    enabled: bool = Field(True, description="Whether this skill is active")