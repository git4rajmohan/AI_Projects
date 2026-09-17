"""Advanced model routing — selects the best model based on task complexity.

Matches instruction.md section 49 rule 3 ("Do not couple the system to a single LLM provider")
and Phase 9 ("Advanced model routing").

The router analyzes the task/agent and selects the appropriate model:
- Simple tasks (file conversion, calculations) → fast model (gpt-oss:20b)
- Complex tasks (multi-agent planning, research) → reasoning model (gpt-oss:120b)
- Explicit model override → use the specified model

Routing factors:
- Task type (from intent parser)
- Number of agents in the plan
- Tool complexity (READ only vs EXTERNAL_ACTION)
- Agent goal complexity (heuristic: length and keywords)
- User-specified model override
"""

import logging
from typing import Any

from app.core.config import settings
from app.llm.config import get_model
from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec
from app.planner.intent import Intent, parse_intent

logger = logging.getLogger(__name__)

# Model tiers
MODEL_TIER_FAST = "fast"
MODEL_TIER_DEFAULT = "default"
MODEL_TIER_REASONING = "reasoning"

# Model names per tier (can be overridden via settings)
MODEL_NAMES = {
    MODEL_TIER_FAST: "openai/gpt-oss:20b",
    MODEL_TIER_DEFAULT: "openai/gpt-oss:120b",
    MODEL_TIER_REASONING: "openai/gpt-oss:120b",  # Same as default for now; can be changed
}

# Task types that map to model tiers
TASK_TYPE_TIERS = {
    "qa": MODEL_TIER_FAST,
    "data_analysis": MODEL_TIER_DEFAULT,
    "coding": MODEL_TIER_DEFAULT,
    "document": MODEL_TIER_FAST,
    "business": MODEL_TIER_REASONING,
    "automation": MODEL_TIER_FAST,
    "research": MODEL_TIER_REASONING,
    "other": MODEL_TIER_DEFAULT,
}

# Keywords that suggest complex reasoning
COMPLEXITY_KEYWORDS = {
    "analyze", "compare", "evaluate", "investigate", "design", "architect",
    "optimize", "strategy", "recommend", "assess", "diagnose", "troubleshoot",
    "multi-step", "complex", "comprehensive", "detailed",
}


class ModelRouter:
    """Routes tasks to the appropriate model based on complexity.

    Usage:
        router = ModelRouter()
        model = router.select_model(intent_text="Analyze sales data", agent_spec=spec)
    """

    def __init__(self) -> None:
        # Allow overriding model names via settings
        self._model_names = {
            MODEL_TIER_FAST: settings.llm_model if "fast" not in settings.llm_model else MODEL_NAMES[MODEL_TIER_FAST],
            MODEL_TIER_DEFAULT: settings.llm_model,
            MODEL_TIER_REASONING: settings.llm_model,
        }

    def select_tier(
        self,
        intent_text: str = "",
        agent_spec: AgentSpec | None = None,
        plan: PlanSpec | None = None,
    ) -> str:
        """Determine the model tier for a task.

        Args:
            intent_text: The user's intent text.
            agent_spec: The agent spec (if selecting for a specific agent).
            plan: The full plan (if selecting for a plan).

        Returns:
            One of MODEL_TIER_FAST, MODEL_TIER_DEFAULT, MODEL_TIER_REASONING.
        """
        # If agent has an explicit model, use it
        if agent_spec and agent_spec.model:
            logger.debug(f"Agent '{agent_spec.id}' has explicit model: {agent_spec.model}")
            return MODEL_TIER_DEFAULT  # Respect the explicit model in get_model_for_tier

        # Parse intent to get task type
        intent: Intent | None = None
        if intent_text:
            intent = parse_intent(intent_text)

        # Start with task type mapping
        tier = MODEL_TIER_DEFAULT
        if intent and intent.task_type in TASK_TYPE_TIERS:
            tier = TASK_TYPE_TIERS[intent.task_type]

        # Upgrade to reasoning if complexity keywords are present
        if intent_text:
            text_lower = intent_text.lower()
            if any(kw in text_lower for kw in COMPLEXITY_KEYWORDS):
                tier = MODEL_TIER_REASONING

        # Downgrade to fast for simple single-agent plans with only READ tools
        if plan and len(plan.agents) == 1:
            agent = plan.agents[0]
            if all(t in ("file_reader", "calculator") for t in agent.tools):
                tier = MODEL_TIER_FAST

        if agent_spec:
            # Check if agent only uses simple tools
            if all(t in ("file_reader", "calculator") for t in agent_spec.tools):
                if tier == MODEL_TIER_DEFAULT:
                    tier = MODEL_TIER_FAST

        logger.debug(f"Selected model tier: {tier} (intent_type={intent.task_type if intent else 'unknown'})")
        return tier

    def get_model_for_tier(self, tier: str, model_override: str = "") -> Any:
        """Get a LiteLlm model instance for the given tier.

        Args:
            tier: One of MODEL_TIER_FAST, MODEL_TIER_DEFAULT, MODEL_TIER_REASONING.
            model_override: Explicit model name to use (takes precedence).

        Returns:
            LiteLlm model instance.
        """
        if model_override:
            return get_model(model_override)

        model_name = self._model_names.get(tier, self._model_names[MODEL_TIER_DEFAULT])
        return get_model(model_name)

    def select_model(
        self,
        intent_text: str = "",
        agent_spec: AgentSpec | None = None,
        plan: PlanSpec | None = None,
    ) -> Any:
        """Select and return the appropriate model for a task.

        This is the main entry point — analyzes the task and returns
        a LiteLlm model instance.

        Args:
            intent_text: The user's intent text.
            agent_spec: The agent spec (if selecting for a specific agent).
            plan: The full plan (if selecting for a plan).

        Returns:
            LiteLlm model instance.
        """
        tier = self.select_tier(intent_text, agent_spec, plan)
        override = agent_spec.model if agent_spec and agent_spec.model else ""
        return self.get_model_for_tier(tier, override)

    def get_routing_info(
        self,
        intent_text: str = "",
        agent_spec: AgentSpec | None = None,
        plan: PlanSpec | None = None,
    ) -> dict[str, Any]:
        """Get routing information without creating a model instance.

        Useful for API responses and debugging.

        Returns:
            Dict with tier, model_name, and routing reasons.
        """
        tier = self.select_tier(intent_text, agent_spec, plan)
        model_name = self._model_names.get(tier, self._model_names[MODEL_TIER_DEFAULT])

        intent = parse_intent(intent_text) if intent_text else None

        reasons: list[str] = []
        if intent:
            reasons.append(f"task_type={intent.task_type} → tier={TASK_TYPE_TIERS.get(intent.task_type, MODEL_TIER_DEFAULT)}")
        if intent_text and any(kw in intent_text.lower() for kw in COMPLEXITY_KEYWORDS):
            reasons.append("complexity keywords detected → upgraded to reasoning")
        if plan and len(plan.agents) == 1:
            reasons.append(f"single-agent plan → simplified tier")
        if agent_spec and agent_spec.model:
            reasons.append(f"explicit model override: {agent_spec.model}")

        return {
            "tier": tier,
            "model_name": model_name,
            "task_type": intent.task_type if intent else "unknown",
            "reasons": reasons,
        }


# --- Singleton ---

_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """Get the singleton ModelRouter instance."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router