"""Skill recommendation engine — suggests skills based on user intent and history.

Matches instruction.md section 11 (Skill Discovery) and Phase 9 ("Skill recommendation").

The recommendation engine goes beyond simple keyword matching (Phase 2's discovery):
1. Keyword matching (existing discovery)
2. Usage history — skills that were successfully used for similar intents
3. Success rate — prefer skills with high success rates
4. Recency — boost recently used skills
5. Tag similarity — match on tag overlap

Returns ranked recommendations with scores and explanations.
"""

import logging
from typing import Any

from sqlalchemy import select

from app.db import database
from app.models.skill import SkillModel, SkillVersionModel
from app.skills.discovery import SkillMatch, discover_skills
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


class SkillRecommendation:
    """A single skill recommendation with explanation."""

    def __init__(
        self,
        skill_id: str,
        skill_name: str,
        score: float,
        reason: str,
        version: str = "",
        description: str = "",
        usage_count: int = 0,
        success_rate: float = 0.0,
    ) -> None:
        self.skill_id = skill_id
        self.skill_name = skill_name
        self.score = score
        self.reason = reason
        self.version = version
        self.description = description
        self.usage_count = usage_count
        self.success_rate = success_rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "score": round(self.score, 4),
            "reason": self.reason,
            "version": self.version,
            "description": self.description,
            "usage_count": self.usage_count,
            "success_rate": round(self.success_rate, 4),
        }


class SkillRecommender:
    """Recommends skills based on intent, usage history, and success rates.

    Usage:
        recommender = SkillRecommender()
        recommendations = await recommender.recommend("Analyze sales data")
    """

    async def recommend(
        self,
        intent_text: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> list[SkillRecommendation]:
        """Recommend skills for a given user intent.

        Combines:
        - Keyword matching score (from discovery)
        - Success rate boost (skills with >80% success rate get +0.1)
        - Usage count boost (frequently used skills get +0.05, capped)
        - Recency boost (recently used skills get +0.05)

        Args:
            intent_text: The user's natural-language intent.
            max_results: Maximum number of recommendations.
            min_score: Minimum recommendation score.

        Returns:
            List of SkillRecommendation objects, sorted by score.
        """
        # Step 1: Get keyword matches from discovery
        async with database.async_session_factory() as session:
            matches = await discover_skills(intent_text, session, min_score=0.0, max_results=20)

        if not matches:
            logger.info("No skills found for recommendation")
            return []

        # Step 2: Enrich with usage metrics and compute final scores
        recommendations: list[SkillRecommendation] = []

        for match in matches:
            skill = match.skill
            version = match.version

            # Base score from keyword matching
            score = match.score

            # Success rate boost
            total_usage = skill.usage_count
            success_rate = 0.0
            if total_usage > 0:
                success_rate = skill.success_count / total_usage
                if success_rate >= 0.8:
                    score += 0.1
                elif success_rate >= 0.5:
                    score += 0.05
                elif success_rate < 0.3 and total_usage > 2:
                    # Penalize skills with poor track record
                    score -= 0.1

            # Usage count boost (capped)
            if total_usage > 0:
                usage_boost = min(total_usage * 0.01, 0.05)
                score += usage_boost

            # Recency boost (if used in last 7 days)
            if version.last_used:
                from datetime import datetime, timezone, timedelta

                days_since = (datetime.now(timezone.utc) - version.last_used).days
                if days_since < 7:
                    score += 0.05 * (1 - days_since / 7)

            # Cap score at 1.0
            score = min(score, 1.0)

            # Build reason explanation
            reasons: list[str] = []
            if match.score > 0.3:
                reasons.append(f"keyword match ({match.score:.2f})")
            if success_rate >= 0.8:
                reasons.append(f"high success rate ({success_rate:.0%})")
            if total_usage > 0:
                reasons.append(f"used {total_usage} time(s)")
            if version.last_used:
                reasons.append(f"last used {version.last_used.strftime('%Y-%m-%d')}")

            reason = "; ".join(reasons) if reasons else "weak keyword match"

            if score >= min_score:
                recommendations.append(SkillRecommendation(
                    skill_id=skill.id,
                    skill_name=skill.name,
                    score=score,
                    reason=reason,
                    version=version.version,
                    description=skill.description,
                    usage_count=total_usage,
                    success_rate=success_rate,
                ))

        # Sort by score descending
        recommendations.sort(key=lambda r: r.score, reverse=True)
        recommendations = recommendations[:max_results]

        logger.info(
            f"Recommended {len(recommendations)} skills for intent: "
            f"{intent_text[:80]}..."
        )

        return recommendations


# --- Singleton ---

_recommender: SkillRecommender | None = None


def get_skill_recommender() -> SkillRecommender:
    """Get the singleton SkillRecommender instance."""
    global _recommender
    if _recommender is None:
        _recommender = SkillRecommender()
    return _recommender