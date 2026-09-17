"""Pydantic schemas for tools.

ToolSpec defines a tool available to agents.
Matches instruction.md section 8 (ToolSpec).
"""

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Specification for a tool."""

    id: str = Field(..., description="Unique tool identifier")
    name: str = Field(..., description="Human-readable tool name")
    description: str = Field(..., description="What this tool does")

    input_schema: dict = Field(default_factory=dict, description="Input JSON schema")
    output_schema: dict = Field(default_factory=dict, description="Output JSON schema")

    permission_level: str = Field("READ", description="Permission level: READ, WRITE, EXTERNAL_ACTION, DESTRUCTIVE")

    enabled: bool = Field(True, description="Whether this tool is active")