"""Pydantic schema for evaluation results.

Matches instruction.md section 23 (Evaluation Engine).
"""

from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    """Result of evaluating a completed workflow."""

    success: bool = Field(..., description="Whether the evaluation passed")
    score: float = Field(..., ge=0.0, le=1.0, description="Overall score")
    criteria: dict[str, float] = Field(default_factory=dict, description="Per-criterion scores")
    issues: list[str] = Field(default_factory=list, description="Issues found")
    recommendations: list[str] = Field(default_factory=list, description="Recommendations for improvement")