"""Tests for the model router and skill recommender.

Phase 9: Advanced Features
"""

import pytest

from app.llm.router import (
    MODEL_TIER_DEFAULT,
    MODEL_TIER_FAST,
    MODEL_TIER_REASONING,
    ModelRouter,
    get_model_router,
)
from app.models.agent import AgentSpec
from app.models.plan_schema import PlanSpec
from app.skills.recommender import SkillRecommender, get_skill_recommender


class TestModelRouter:
    """Test the ModelRouter."""

    def test_simple_task_uses_fast(self):
        """Simple tasks with only READ tools use fast tier."""
        router = ModelRouter()
        agent = AgentSpec(
            id="simple",
            name="Simple",
            goal="Read a file",
            tools=["file_reader", "calculator"],
        )

        tier = router.select_tier(intent_text="Convert this CSV", agent_spec=agent)
        assert tier == MODEL_TIER_FAST

    def test_research_task_uses_reasoning(self):
        """Research tasks use reasoning tier."""
        router = ModelRouter()
        tier = router.select_tier(intent_text="Research five AI testing tools and compare them")
        assert tier == MODEL_TIER_REASONING

    def test_complexity_keywords_upgrade(self):
        """Complexity keywords upgrade to reasoning tier."""
        router = ModelRouter()
        tier = router.select_tier(intent_text="Analyze and evaluate the data")
        assert tier == MODEL_TIER_REASONING

    def test_explicit_model_override(self):
        """Agent with explicit model uses default tier (respects override)."""
        router = ModelRouter()
        agent = AgentSpec(
            id="custom",
            name="Custom",
            goal="Custom task",
            model="openai/some-model",
            tools=["web_search"],
        )

        tier = router.select_tier(intent_text="Search the web", agent_spec=agent)
        # Explicit model → returns default tier (get_model_for_tier respects override)
        assert tier == MODEL_TIER_DEFAULT

    def test_single_agent_plan_simplifies(self):
        """Single-agent plan with simple tools uses fast tier."""
        router = ModelRouter()
        agent = AgentSpec(
            id="solo",
            name="Solo",
            goal="Simple task",
            tools=["file_reader"],
        )
        plan = PlanSpec(
            task_id="t1",
            objective="Simple",
            agents=[agent],
        )

        tier = router.select_tier(intent_text="Read a file", plan=plan)
        assert tier == MODEL_TIER_FAST

    def test_routing_info(self):
        """get_routing_info returns tier, model, and reasons."""
        router = ModelRouter()
        info = router.get_routing_info(intent_text="Research AI tools")

        assert "tier" in info
        assert "model_name" in info
        assert "reasons" in info
        assert isinstance(info["reasons"], list)

    def test_singleton(self):
        """get_model_router returns a singleton."""
        r1 = get_model_router()
        r2 = get_model_router()
        assert r1 is r2


class TestSkillRecommender:
    """Test the SkillRecommender."""

    @pytest.mark.asyncio
    async def test_recommend_no_skills(self):
        """Recommender returns empty list when no skills exist."""
        recommender = SkillRecommender()
        results = await recommender.recommend("nonexistent task type xyz123")
        assert results == []

    @pytest.mark.asyncio
    async def test_recommend_with_skills(self):
        """Recommender returns skills that match the intent."""
        # Create a skill first
        from app.models.skill_schema import SkillSpec
        from app.skills.registry import get_skill_registry

        registry = get_skill_registry()
        spec = SkillSpec(
            id="",
            name="CSV File Converter",
            description="Convert CSV files to Excel format for data analysis",
            version="1.0.0",
            tags=["csv", "excel", "conversion"],
            agents=["converter"],
            tools=["file_reader", "file_writer"],
            workflow={"type": "dag", "nodes": [], "edges": []},
            evaluation={"criteria": ["accuracy"], "threshold": 0.7},
            permissions={"file_read": True},
        )
        await registry.create_skill(spec)

        recommender = SkillRecommender()
        results = await recommender.recommend("Convert this CSV into an Excel file")

        assert len(results) >= 1
        assert any("CSV" in r.skill_name for r in results)

    @pytest.mark.asyncio
    async def test_recommend_includes_score(self):
        """Recommendations include a score."""
        from app.models.skill_schema import SkillSpec
        from app.skills.registry import get_skill_registry

        registry = get_skill_registry()
        spec = SkillSpec(
            id="",
            name="Data Analysis Skill",
            description="Analyze data and generate insights",
            version="1.0.0",
            tags=["data", "analysis"],
            agents=["analyst"],
            tools=["python_executor"],
            workflow={"type": "dag", "nodes": [], "edges": []},
            evaluation={"criteria": ["accuracy"], "threshold": 0.7},
            permissions={},
        )
        await registry.create_skill(spec)

        recommender = SkillRecommender()
        results = await recommender.recommend("Analyze data and generate insights")

        for r in results:
            assert 0.0 <= r.score <= 1.0
            assert r.reason  # Non-empty reason

    @pytest.mark.asyncio
    async def test_recommend_max_results(self):
        """Recommender respects max_results."""
        recommender = SkillRecommender()
        results = await recommender.recommend("test", max_results=2)
        assert len(results) <= 2

    def test_singleton(self):
        """get_skill_recommender returns a singleton."""
        r1 = get_skill_recommender()
        r2 = get_skill_recommender()
        assert r1 is r2