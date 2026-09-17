"""LLM Planner — generates structured plans from user intent using ADK LlmAgent.

Matches instruction.md section 10 (Planner Responsibilities) and section 12 (Agent Blueprint).

Architecture:
  User Intent → Intent Parser → Skill Discovery → LLM Planner → Plan Validator → PlanSpec

The Planner is an ADK LlmAgent with output_schema set to a Pydantic model.
It uses LiteLlm with Ollama Cloud (no proxy needed).
output_schema is used WITHOUT tools (non-Gemini model limitation).

Key design decisions:
- The LLM generates a PlannerOutput (without task_id — injected after parsing)
- The PlannerOutput schema is designed to be LLM-friendly with clear field descriptions
- After parsing, we validate and convert to PlanSpec
"""

import json
import logging
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from app.llm.config import get_model
from app.models.agent import AgentSpec
from app.models.plan_schema import (
    EvaluationSpec,
    MemorySpec,
    PlanSpec,
    WorkflowSpec,
)
from app.planner.intent import Intent, parse_intent
from app.planner.plan_validator import PlanValidationError, validate_plan_json

logger = logging.getLogger(__name__)

# --- LLM-facing output schema ---
# This is what the LLM produces. It's similar to PlanSpec but without task_id
# (which we inject after parsing) and with simpler field names for LLM clarity.


class PlannerAgentSpec(BaseModel):
    """Agent specification for the LLM to fill in."""

    model_config = ConfigDict(extra='ignore')

    id: str = Field(..., description="Unique agent identifier, e.g. 'data_analyst'")
    name: str = Field("", description="Human-readable name, e.g. 'Data Analyst'")
    description: str = Field("", description="What this agent does")
    goal: str = Field("", description="The agent's primary goal")
    tools: list[str] = Field(
        default_factory=list,
        description="Tool IDs: file_reader, file_writer, python_executor, web_search, http_request, calculator",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Agent IDs this agent depends on (must run after them)",
    )
    requires_human_approval: bool = Field(False, description="Whether this agent needs human approval")


class PlannerOutput(BaseModel):
    """Structured output schema for the LLM Planner.

    The LLM fills this in based on the user's intent.
    We then convert it to a full PlanSpec.
    """

    model_config = ConfigDict(extra='ignore')

    objective: str = Field("", description="What the plan aims to achieve")
    summary: str = Field("", description="Brief one-sentence plan summary")
    agents: list[PlannerAgentSpec] = Field(
        default_factory=list,
        description="Agents to create. Use minimum number needed. For simple tasks, use 1 agent.",
    )
    workflow_type: str = Field(
        "dag",
        description="Workflow type: dag, sequential, parallel",
    )
    evaluation_criteria: list[str] = Field(
        default_factory=list,
        description="Evaluation criteria: accuracy, completeness, format, relevance",
    )
    estimated_cost: float = Field(0.0, ge=0.0, description="Estimated cost in USD")
    estimated_duration_seconds: int = Field(
        60, ge=1, description="Estimated execution time in seconds"
    )
    requires_approval: bool = Field(
        True, description="Whether user approval is required before execution"
    )


# --- System prompt for the planner ---
PLANNER_SYSTEM_PROMPT = """You are a Planning Agent for an Agentic AI Workflow Platform.

Your job: analyze a user's intent and create a structured execution plan.

## Rules

1. Use the MINIMUM number of agents required. For simple tasks (e.g., "convert CSV to Excel"), use just 1 agent.
2. For complex tasks, create multiple agents with clear dependencies.
3. Agents that can run in parallel should NOT depend on each other.
4. Available tools: file_reader, file_writer, python_executor, web_search, http_request, calculator
5. Every agent must have a unique id (snake_case, e.g. "data_analyst")
6. Every agent must have a clear goal
7. Dependencies must reference other agent IDs
8. Estimate cost and time realistically
9. Set requires_approval=true for any plan involving external actions (web search, HTTP requests) or destructive operations
10. Do NOT create unnecessary agents. If one agent can do it, use one agent.

## Examples

### Simple task: "Convert this CSV to Excel"
- 1 agent: file_converter (tools: file_reader, file_writer)
- No dependencies
- Cost: ~$0.01, Time: ~10s

### Complex task: "Research 5 AI testing tools and compare them"
- 5 parallel research agents (tools: web_search) — no dependencies between them
- 1 comparison agent (depends on all 5 research agents)
- 1 report agent (depends on comparison agent)
- Cost: ~$0.50, Time: ~180s

### Data analysis: "Analyze sales data and explain revenue decline"
- 1 data_analyst (tools: file_reader, python_executor)
- 1 customer_analyst (tools: python_executor, depends on data_analyst)
- 1 report_writer (depends on customer_analyst)
- Cost: ~$0.30, Time: ~120s

## Output

You MUST return a JSON object with EXACTLY this structure. Do NOT include any text, reasoning, or explanation outside the JSON. Do NOT wrap it in markdown code blocks.

```json
{
  "objective": "What the plan aims to achieve",
  "summary": "Brief one-sentence plan summary",
  "agents": [
    {
      "id": "agent_id_snake_case",
      "name": "Human Readable Name",
      "description": "What this agent does",
      "goal": "The agent's primary goal",
      "tools": ["file_reader", "file_writer"],
      "dependencies": [],
      "requires_human_approval": false
    }
  ],
  "workflow_type": "dag",
  "evaluation_criteria": ["accuracy", "completeness"],
  "estimated_cost": 0.01,
  "estimated_duration_seconds": 10,
  "requires_approval": false
}
```

Return ONLY the JSON object. No other text."""


class LLMPlanner:
    """Planner that uses an ADK LlmAgent to generate structured plans.

    Usage:
        planner = LLMPlanner()
        plan = await planner.create_plan(task_id="...", intent="Analyze sales data")
    """

    def __init__(self, model_name: str | None = None) -> None:
        """Initialize the planner.

        Args:
            model_name: LLM model to use. If None, uses default from settings.
        """
        self._model_name = model_name
        self._agent: LlmAgent | None = None
        self._runner: Runner | None = None
        self._session_service: InMemorySessionService | None = None

    def _get_agent(self) -> LlmAgent:
        """Get or create the ADK LlmAgent for planning."""
        if self._agent is None:
            self._agent = LlmAgent(
                name="planner_agent",
                description="Analyzes user intent and generates a structured execution plan.",
                instruction=PLANNER_SYSTEM_PROMPT,
                # Reasoning models can spend most of a small token budget on hidden
                # chain-of-thought before emitting the JSON — give it more room.
                model=get_model(self._model_name, max_tokens=8192),
                # No output_schema — non-Gemini models (Ollama) don't reliably
                # support structured output. We parse JSON from the text response.
                output_key="plan_output",
            )
        return self._agent

    def _get_runner(self) -> Runner:
        """Get or create the ADK Runner."""
        if self._runner is None:
            self._session_service = InMemorySessionService()
            self._runner = Runner(
                agent=self._get_agent(),
                app_name="agentos_planner",
                session_service=self._session_service,
            )
        return self._runner

    async def create_plan(self, task_id: str, intent_text: str) -> PlanSpec:
        """Generate a structured plan from user intent.

        Args:
            task_id: The task ID this plan belongs to.
            intent_text: The user's natural-language intent.

        Returns:
            A validated PlanSpec.

        Raises:
            PlanValidationError: If the LLM output fails validation.
            RuntimeError: If the LLM call fails or returns no output.
        """
        logger.info(f"Planning for task {task_id}: {intent_text[:100]}...")

        # Parse intent (lightweight extraction)
        intent: Intent = parse_intent(intent_text)
        logger.info(f"Parsed intent: type={intent.task_type}, objective={intent.objective[:80]}...")

        # Build the prompt for the LLM
        prompt = self._build_prompt(intent)

        # Run the ADK agent, retrying once with a stricter corrective prompt if the
        # model rambles through reasoning without ever emitting a JSON object.
        plan_data: dict | None = None
        last_error: str = "Planner LLM returned no output"
        for attempt in range(2):
            raw_output = await self._run_agent(prompt)

            if not raw_output:
                last_error = "Planner LLM returned no output"
            else:
                logger.info(f"Planner raw output (attempt {attempt + 1}): {raw_output[:200]}...")
                try:
                    plan_data = json.loads(raw_output)
                except json.JSONDecodeError as e:
                    plan_data = self._extract_json(raw_output)
                    if plan_data is None:
                        last_error = f"LLM output is not valid JSON: {e}. Raw output: {raw_output[:500]}"

            if plan_data is not None:
                break

            if attempt == 0:
                logger.warning(f"Planner attempt 1 produced no valid JSON, retrying with a stricter prompt: {last_error[:150]}")
                prompt = (
                    f"{self._build_prompt(intent)}\n\n"
                    "IMPORTANT: Your previous response did not contain a valid JSON object. "
                    "Do NOT include any reasoning, analysis, or explanation this time. "
                    "Respond with ONLY the raw JSON object, starting with '{' and ending with '}'."
                )

        if plan_data is None:
            raise PlanValidationError([last_error])

        # Post-process: fill in missing fields that the LLM might omit
        if not plan_data.get("objective"):
            plan_data["objective"] = intent.objective or intent.raw_text
        if not plan_data.get("summary"):
            plan_data["summary"] = f"Plan for: {intent.raw_text[:100]}"
        if not plan_data.get("agents"):
            raise PlanValidationError(["Plan has no agents"])
        for agent in plan_data["agents"]:
            if isinstance(agent, dict):
                if not agent.get("name"):
                    agent["name"] = agent.get("id", "Agent").replace("_", " ").title()
                if not agent.get("goal"):
                    agent["goal"] = agent.get("description", "Execute the task")
                if not agent.get("description"):
                    agent["description"] = agent.get("goal", "")

        # Validate and convert to PlanSpec
        plan = validate_plan_json(plan_data, task_id)

        logger.info(
            f"Plan created: {len(plan.agents)} agents, "
            f"cost=${plan.estimated_cost:.2f}, "
            f"time={plan.estimated_duration_seconds}s"
        )

        return plan

    def _build_prompt(self, intent: Intent) -> str:
        """Build the prompt for the LLM planner."""
        parts = [
            f"User Intent: {intent.raw_text}",
            f"Inferred Task Type: {intent.task_type}",
        ]
        if intent.constraints:
            parts.append(f"Constraints: {', '.join(intent.constraints)}")
        parts.append(
            "\nAnalyze this intent and create a structured plan. "
            "Return ONLY the JSON object matching the schema."
        )
        return "\n".join(parts)

    async def _run_agent(self, prompt: str) -> str | None:
        """Run the ADK agent and extract the final response text.

        Returns the raw JSON string from the LLM, or None if no response.
        """
        runner = self._get_runner()
        session_id = f"plan_{uuid.uuid4().hex[:8]}"

        # Create session
        await self._session_service.create_session(
            app_name="agentos_planner",
            user_id="planner",
            session_id=session_id,
        )

        # Build user message
        user_message = types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        )

        # Run and collect final response
        final_text: str | None = None
        async for event in runner.run_async(
            user_id="planner",
            session_id=session_id,
            new_message=user_message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                # Collect all text parts (reasoning models may split output)
                text_parts = []
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
                final_text = "\n".join(text_parts).strip()

        # Cleanup session
        try:
            await self._session_service.delete_session(
                app_name="agentos_planner",
                user_id="planner",
                session_id=session_id,
            )
        except Exception:
            pass  # Best-effort cleanup

        return final_text

    def _extract_json(self, text: str) -> dict | None:
        """Try to extract JSON from text that might be wrapped in markdown.

        Handles cases like:
        - ```json\n{...}\n```
        - Here is the plan: {...}
        """
        # Try markdown code block
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            json_str = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            json_str = text[start:end].strip()
        else:
            # Try to find the first { and last }
            first = text.find("{")
            last = text.rfind("}")
            if first != -1 and last != -1 and last > first:
                json_str = text[first : last + 1]
            else:
                return None

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None


# Singleton planner instance
_planner: LLMPlanner | None = None


def get_planner() -> LLMPlanner:
    """Get the singleton LLMPlanner instance."""
    global _planner
    if _planner is None:
        _planner = LLMPlanner()
    return _planner