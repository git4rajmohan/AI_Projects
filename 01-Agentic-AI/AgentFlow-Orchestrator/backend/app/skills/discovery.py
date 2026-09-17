"""Skill discovery — searches the skill registry for matching skills.

Matches instruction.md section 11 (Skill Discovery) and section 54 (Skill Discovery and Reuse).

MVP: keyword-based matching. Phase 9 will add semantic/vector matching.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import SkillModel, SkillVersionModel

logger = logging.getLogger(__name__)


class SkillMatch:
    """A skill that matched a user intent."""

    def __init__(self, skill: SkillModel, version: SkillVersionModel, score: float):
        self.skill = skill
        self.version = version
        self.score = score  # 0.0 to 1.0

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill.id,
            "skill_name": self.skill.name,
            "version": self.version.version,
            "score": self.score,
            "description": self.skill.description,
        }


async def discover_skills(
    intent_text: str,
    db: AsyncSession,
    min_score: float = 0.1,
    max_results: int = 5,
) -> list[SkillMatch]:
    """Search the skill registry for skills matching the user intent.

    MVP: keyword matching on skill name + description + tags.
    Future: semantic similarity via embeddings.

    Args:
        intent_text: The user's natural-language intent.
        db: Database session.
        min_score: Minimum match score (0.0 to 1.0).
        max_results: Maximum number of matches to return.

    Returns:
        List of SkillMatch objects, sorted by score (highest first).
    """
    # Get all enabled skills with their active versions
    result = await db.execute(
        select(SkillModel, SkillVersionModel)
        .join(SkillVersionModel, SkillModel.id == SkillVersionModel.skill_id)
        .where(SkillModel.enabled == True)  # noqa: E712
        .where(SkillVersionModel.is_active == True)  # noqa: E712
        .order_by(SkillModel.name)
    )
    rows = result.all()

    if not rows:
        logger.info("No skills in registry — planner will generate new plan")
        return []

    # Keyword matching
    intent_lower = intent_text.lower()
    intent_words = set(_tokenize(intent_lower))

    matches: list[SkillMatch] = []
    for skill, version in rows:
        score = _calculate_match_score(intent_lower, intent_words, skill)
        if score >= min_score:
            matches.append(SkillMatch(skill, version, score))

    # Sort by score descending, take top N
    matches.sort(key=lambda m: m.score, reverse=True)
    matches = matches[:max_results]

    if matches:
        logger.info(f"Found {len(matches)} matching skills: {[m.skill.name for m in matches]}")
    else:
        logger.info("No matching skills found — planner will generate new plan")

    return matches


def _tokenize(text: str) -> list[str]:
    """Simple tokenization for keyword matching."""
    # Remove common stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "and", "or", "but", "not", "to", "of", "in", "on", "at",
        "for", "with", "by", "from", "as", "this", "that", "these",
        "those", "i", "want", "need", "please", "can", "you",
    }
    # Split on non-alphanumeric
    import re

    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in stop_words and len(t) > 2]


def _calculate_match_score(intent_lower: str, intent_words: set[str], skill: SkillModel) -> float:
    """Calculate a keyword match score between intent and skill.

    Score is based on:
    - Direct keyword matches in skill name (weight: 3x)
    - Keyword matches in description (weight: 1x)
    - Tag matches (weight: 2x)

    Returns a score from 0.0 to 1.0.
    """
    score = 0.0
    max_score = 0.0

    # Name matches (highest weight)
    name_words = set(_tokenize(skill.name.lower()))
    if name_words:
        name_overlap = len(intent_words & name_words)
        score += name_overlap * 3.0
        max_score += len(name_words) * 3.0

    # Tag matches
    tags = skill.tags or []
    tag_words = set()
    for tag in tags:
        tag_words.update(_tokenize(tag.lower()))
    if tag_words:
        tag_overlap = len(intent_words & tag_words)
        score += tag_overlap * 2.0
        max_score += len(tag_words) * 2.0

    # Description matches
    desc_words = set(_tokenize(skill.description.lower()))
    if desc_words:
        desc_overlap = len(intent_words & desc_words)
        score += desc_overlap * 1.0
        max_score += len(desc_words) * 1.0

    # Direct substring match bonus
    if skill.name.lower() in intent_lower:
        score += 5.0
        max_score += 5.0

    if max_score == 0:
        return 0.0

    return min(score / max_score, 1.0)