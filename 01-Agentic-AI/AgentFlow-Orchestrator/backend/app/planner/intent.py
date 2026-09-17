"""Intent parsing — extracts structured information from user intent.

Matches instruction.md section 3.2 (Intent) and section 10 (Planner Responsibilities).
"""

from pydantic import BaseModel, Field


class Intent(BaseModel):
    """Parsed user intent.

    The Planner uses this to understand what the user wants
    before generating a plan.
    """

    raw_text: str = Field(..., description="Original user intent text")
    objective: str = Field("", description="Extracted objective")
    task_type: str = Field("", description="Inferred task type: research, data_analysis, coding, qa, document, business, automation, other")
    constraints: list[str] = Field(default_factory=list, description="Any constraints mentioned")
    expected_output: str = Field("", description="What the user expects as output")


def parse_intent(raw_text: str) -> Intent:
    """Parse a raw user intent string into a structured Intent object.

    For MVP, this is a lightweight extraction — the LLM Planner
    does the heavy lifting. This just provides basic structure.
    """
    # Simple heuristic extraction for MVP
    text = raw_text.strip()

    # Infer task type from keywords — order matters: more specific types first
    task_type = "other"
    text_lower = text.lower()
    type_keywords = {
        "qa": ["test case", "test cases", "qa", "regression", "bug", "test automation", "automated test"],
        "data_analysis": ["excel", "csv", "kpi", "revenue", "sales data", "data analysis", "anomaly", "trends"],
        "coding": ["create", "build", "code", "api", "application", "function", "script", "rest api"],
        "document": ["summarize", "document", "pdf", "report", "extract", "contract"],
        "business": ["business", "customer", "churn", "marketing", "financial", "management"],
        "automation": ["automate", "workflow", "schedule", "recurring", "pipeline"],
        "research": ["research", "compare", "find", "search", "investigate"],
    }
    for t, keywords in type_keywords.items():
        if any(kw in text_lower for kw in keywords):
            task_type = t
            break

    # Extract objective (first sentence or full text if short)
    objective = text.split(".")[0] if "." in text else text
    if len(objective) > 200:
        objective = objective[:200] + "..."

    return Intent(
        raw_text=text,
        objective=objective,
        task_type=task_type,
        constraints=[],
        expected_output="",
    )