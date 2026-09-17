"""Skill Registry — CRUD operations for skills and skill versions.

Matches instruction.md section 11 (Skill Discovery), section 25 (Skill Creation),
section 26 (Skill Content), and section 27 (Skill Versioning).

The registry manages:
- Creating skills (with initial version 1.0.0)
- Creating new versions of existing skills (semantic versioning)
- Activating/deactivating versions
- Listing skills with their active versions
- Updating skill metadata (tags, description, enabled)
- Deleting skills (soft delete — sets enabled=False)
- Tracking usage metrics (usage_count, success_count, etc.)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import database
from app.models.skill import SkillModel, SkillVersionModel
from app.models.skill_schema import SkillSpec

logger = logging.getLogger(__name__)


class SkillNotFoundError(Exception):
    """Raised when a requested skill is not found."""


class SkillVersionNotFoundError(Exception):
    """Raised when a requested skill version is not found."""


class SkillRegistry:
    """Registry for managing skills and their versions.

    All methods create their own DB sessions internally (non-DI pattern)
    so they can be called from background tasks and API routes alike.
    For tests, the session factory is patched via conftest.py.
    """

    async def create_skill(
        self,
        spec: SkillSpec,
        author: str | None = None,
    ) -> dict[str, Any]:
        """Create a new skill with an initial version.

        Args:
            spec: The SkillSpec defining the skill.
            author: Optional author name.

        Returns:
            Dict with skill_id, version_id, and version string.
        """
        skill_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())

        async with database.async_session_factory() as session:
            # Create skill
            skill = SkillModel(
                id=skill_id,
                name=spec.name,
                description=spec.description,
                author=author or spec.author,
                tags=spec.tags,
                enabled=spec.enabled,
            )
            session.add(skill)

            # Create initial version (1.0.0)
            version = SkillVersionModel(
                id=version_id,
                skill_id=skill_id,
                version=spec.version or "1.0.0",
                is_active=True,
                spec_data=spec.model_dump(),
            )
            session.add(version)
            await session.commit()

        logger.info(f"Created skill '{spec.name}' (id={skill_id}, version={spec.version or '1.0.0'})")
        return {
            "skill_id": skill_id,
            "version_id": version_id,
            "version": spec.version or "1.0.0",
        }

    async def create_version(
        self,
        skill_id: str,
        spec: SkillSpec,
        activate: bool = True,
    ) -> dict[str, Any]:
        """Create a new version of an existing skill.

        Args:
            skill_id: The skill ID to add a version to.
            spec: The SkillSpec for the new version.
            activate: If True, deactivate all other versions and activate this one.

        Returns:
            Dict with version_id and version string.

        Raises:
            SkillNotFoundError: If the skill doesn't exist.
        """
        version_id = str(uuid.uuid4())

        async with database.async_session_factory() as session:
            # Verify skill exists
            result = await session.execute(
                select(SkillModel).where(SkillModel.id == skill_id)
            )
            skill = result.scalar_one_or_none()
            if skill is None:
                raise SkillNotFoundError(f"Skill '{skill_id}' not found")

            if activate:
                # Deactivate all existing versions
                await session.execute(
                    update(SkillVersionModel)
                    .where(SkillVersionModel.skill_id == skill_id)
                    .values(is_active=False)
                )

            # Create new version
            version = SkillVersionModel(
                id=version_id,
                skill_id=skill_id,
                version=spec.version,
                is_active=activate,
                spec_data=spec.model_dump(),
            )
            session.add(version)

            # Update skill metadata
            skill.name = spec.name
            skill.description = spec.description
            skill.tags = spec.tags
            skill.enabled = spec.enabled

            await session.commit()

        logger.info(f"Created version {spec.version} for skill '{skill_id}'")
        return {
            "version_id": version_id,
            "version": spec.version,
        }

    async def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        """Get a skill with its active version.

        Returns:
            Dict with skill metadata and active version's spec_data,
            or None if not found.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(SkillModel, SkillVersionModel)
                .join(SkillVersionModel, SkillModel.id == SkillVersionModel.skill_id)
                .where(SkillModel.id == skill_id)
                .where(SkillVersionModel.is_active == True)  # noqa: E712
            )
            row = result.first()
            if row is None:
                # Check if skill exists but has no active version
                skill_result = await session.execute(
                    select(SkillModel).where(SkillModel.id == skill_id)
                )
                skill = skill_result.scalar_one_or_none()
                if skill is None:
                    return None
                # Return skill without version
                d = skill.to_dict()
                d["active_version"] = None
                return d

            skill, version = row
            d = skill.to_dict()
            d["active_version"] = version.to_dict()
            return d

    async def list_skills(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        """List all skills with their active versions.

        Args:
            include_disabled: If True, include disabled skills.

        Returns:
            List of skill dicts with active_version included.
        """
        async with database.async_session_factory() as session:
            query = (
                select(SkillModel, SkillVersionModel)
                .join(SkillVersionModel, SkillModel.id == SkillVersionModel.skill_id, isouter=True)
                .where(SkillVersionModel.is_active == True)  # noqa: E712
            )
            if not include_disabled:
                query = query.where(SkillModel.enabled == True)  # noqa: E712
            query = query.order_by(SkillModel.name)

            result = await session.execute(query)
            rows = result.all()

            skills: list[dict[str, Any]] = []
            for skill, version in rows:
                d = skill.to_dict()
                d["active_version"] = version.to_dict() if version else None
                skills.append(d)

            return skills

    async def update_skill(
        self,
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        """Update skill metadata (not the version spec).

        Returns:
            Updated skill dict, or None if not found.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(SkillModel).where(SkillModel.id == skill_id)
            )
            skill = result.scalar_one_or_none()
            if skill is None:
                return None

            if name is not None:
                skill.name = name
            if description is not None:
                skill.description = description
            if tags is not None:
                skill.tags = tags
            if enabled is not None:
                skill.enabled = enabled

            await session.commit()

        return await self.get_skill(skill_id)

    async def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill and all its versions.

        This is a hard delete. For soft delete, use update_skill(enabled=False).

        Returns:
            True if deleted, False if not found.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(SkillModel).where(SkillModel.id == skill_id)
            )
            skill = result.scalar_one_or_none()
            if skill is None:
                return False

            # Delete all versions first
            versions_result = await session.execute(
                select(SkillVersionModel).where(SkillVersionModel.skill_id == skill_id)
            )
            for version in versions_result.scalars().all():
                await session.delete(version)

            await session.delete(skill)
            await session.commit()

        logger.info(f"Deleted skill '{skill_id}'")
        return True

    async def activate_version(self, skill_id: str, version: str) -> bool:
        """Activate a specific version of a skill (deactivate all others).

        Returns:
            True if activated, False if skill or version not found.
        """
        async with database.async_session_factory() as session:
            # Deactivate all versions
            await session.execute(
                update(SkillVersionModel)
                .where(SkillVersionModel.skill_id == skill_id)
                .values(is_active=False)
            )

            # Activate the specified version
            result = await session.execute(
                update(SkillVersionModel)
                .where(SkillVersionModel.skill_id == skill_id)
                .where(SkillVersionModel.version == version)
                .values(is_active=True)
            )

            if result.rowcount == 0:
                return False

            await session.commit()

        logger.info(f"Activated version {version} for skill '{skill_id}'")
        return True

    async def get_active_version_spec(self, skill_id: str) -> SkillSpec | None:
        """Get the SkillSpec from the active version of a skill.

        Returns:
            SkillSpec object, or None if skill/version not found.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(SkillVersionModel)
                .where(SkillVersionModel.skill_id == skill_id)
                .where(SkillVersionModel.is_active == True)  # noqa: E712
            )
            version = result.scalar_one_or_none()
            if version is None:
                return None

            return SkillSpec(**version.spec_data)

    async def record_usage(
        self,
        skill_id: str,
        success: bool,
        duration_seconds: float = 0.0,
        cost: float = 0.0,
        evaluation_score: float = 0.0,
    ) -> None:
        """Record a skill usage (updates metrics).

        Args:
            skill_id: The skill that was used.
            success: Whether the execution succeeded.
            duration_seconds: Execution duration.
            cost: Execution cost.
            evaluation_score: Evaluation score (0.0 to 1.0).
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(SkillModel).where(SkillModel.id == skill_id)
            )
            skill = result.scalar_one_or_none()
            if skill is None:
                return

            skill.usage_count += 1
            if success:
                skill.success_count += 1
            else:
                skill.failure_count += 1

            # Update running averages
            n = skill.usage_count
            skill.avg_duration_seconds = (
                (skill.avg_duration_seconds * (n - 1) + duration_seconds) / n
            )
            skill.avg_cost = (
                (skill.avg_cost * (n - 1) + cost) / n
            )
            if evaluation_score > 0:
                skill.evaluation_score = (
                    (skill.evaluation_score * (n - 1) + evaluation_score) / n
                )

            # Update last_used on the active version
            version_result = await session.execute(
                select(SkillVersionModel)
                .where(SkillVersionModel.skill_id == skill_id)
                .where(SkillVersionModel.is_active == True)  # noqa: E712
            )
            version = version_result.scalar_one_or_none()
            if version:
                version.last_used = datetime.now(timezone.utc)

            await session.commit()


# --- Singleton ---

_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Get the singleton SkillRegistry instance."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry