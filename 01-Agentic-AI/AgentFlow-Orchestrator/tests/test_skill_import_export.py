"""Tests for skill import/export — .skill.zip packaging and round-trip.

Matches instruction.md section 28 (Skill Import) and Phase 8 acceptance:
"A skill exported from one environment can be imported into another."
"""

import io
import json
import zipfile

import pytest

from app.models.skill_schema import SkillSpec
from app.skills.import_export import (
    SkillExportError,
    SkillImportError,
    export_skill_to_zip,
    import_skill_from_zip,
    skill_spec_to_yaml,
)
from app.skills.registry import get_skill_registry


VALID_YAML = """
name: round-trip-skill
version: 1.0.0
description: A skill for testing round-trip import/export

author: Test
tags:
  - round-trip

agents:
  - id: worker
    name: Worker
    description: Does the work
    goal: Process data
    tools:
      - file_reader
      - calculator
    dependencies: []
    max_iterations: 3
    max_tool_calls: 10
    timeout_seconds: 60

tools:
  - file_reader
  - calculator

workflow:
  type: dag
  nodes:
    - id: worker
  edges: []

evaluation:
  criteria:
    - accuracy
  threshold: 0.7

permissions:
  file_read: true

enabled: true
"""


def _make_zip(yaml_content: str) -> bytes:
    """Create a .skill.zip from YAML content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("skill.yaml", yaml_content)
    return buf.getvalue()


class TestSkillSpecToYaml:
    """Test SkillSpec to YAML conversion."""

    def test_basic_conversion(self):
        """SkillSpec converts to YAML with all fields."""
        spec = SkillSpec(
            id="",
            name="yaml-test",
            description="Test YAML generation",
            version="1.0.0",
            agents=["a1"],
            tools=["file_reader"],
            workflow={"type": "dag"},
            tags=["test"],
            author="Tester",
        )

        yaml_str = skill_spec_to_yaml(spec)
        assert "yaml-test" in yaml_str
        assert "1.0.0" in yaml_str
        assert "file_reader" in yaml_str


class TestExportSkill:
    """Test skill export to .skill.zip."""

    @pytest.mark.asyncio
    async def test_export_skill(self):
        """Export a skill as .skill.zip."""
        registry = get_skill_registry()
        spec = SkillSpec(
            id="",
            name="Exportable Skill",
            description="For export testing",
            version="1.0.0",
            agents=["a1"],
            tools=["file_reader"],
            workflow={"type": "dag", "nodes": [], "edges": []},
            tags=["export"],
        )
        result = await registry.create_skill(spec)

        zip_bytes, filename = await export_skill_to_zip(result["skill_id"])

        assert filename == "exportable_skill.skill.zip"
        assert len(zip_bytes) > 0

        # Verify zip contents
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            assert "skill.yaml" in zf.namelist()
            assert "README.md" in zf.namelist()
            assert "spec.json" in zf.namelist()

            yaml_content = zf.read("skill.yaml").decode("utf-8")
            assert "Exportable Skill" in yaml_content

    @pytest.mark.asyncio
    async def test_export_nonexistent_raises(self):
        """Exporting a non-existent skill raises error."""
        with pytest.raises(SkillExportError):
            await export_skill_to_zip("nonexistent-id")


class TestImportSkill:
    """Test skill import from .skill.zip."""

    @pytest.mark.asyncio
    async def test_import_valid_skill(self):
        """Import a valid .skill.zip installs the skill."""
        zip_bytes = _make_zip(VALID_YAML)

        result = await import_skill_from_zip(zip_bytes, install=True)

        assert result["valid"]
        assert result["installed"]
        assert "skill_id" in result
        assert result["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_import_preview_only(self):
        """Import with install=False validates but doesn't install."""
        zip_bytes = _make_zip(VALID_YAML)

        result = await import_skill_from_zip(zip_bytes, install=False)

        assert result["valid"]
        assert not result["installed"]
        assert "skill_id" not in result

    @pytest.mark.asyncio
    async def test_import_missing_yaml_raises(self):
        """Import without skill.yaml raises error."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("wrong.txt", "no yaml here")

        with pytest.raises(SkillImportError, match="skill.yaml"):
            await import_skill_from_zip(buf.getvalue())

    @pytest.mark.asyncio
    async def test_import_invalid_zip_raises(self):
        """Importing invalid zip raises error."""
        with pytest.raises(SkillImportError, match="Invalid zip"):
            await import_skill_from_zip(b"not a zip file")

    @pytest.mark.asyncio
    async def test_import_security_scan(self):
        """Skills with dangerous patterns are rejected."""
        dangerous_yaml = VALID_YAML + "\n# eval(os.system('rm -rf /'))\n"
        zip_bytes = _make_zip(dangerous_yaml)

        with pytest.raises(SkillImportError, match="Security"):
            await import_skill_from_zip(zip_bytes)

    @pytest.mark.asyncio
    async def test_import_unknown_tool_flagged(self):
        """Skills with unknown tools are flagged (not installed)."""
        yaml_with_bad_tool = VALID_YAML.replace(
            "  - calculator\n",
            "  - nonexistent_tool\n",
        )
        zip_bytes = _make_zip(yaml_with_bad_tool)

        result = await import_skill_from_zip(zip_bytes, install=True)

        assert not result["valid"]
        assert not result["installed"]
        assert any("nonexistent_tool" in i for i in result["validation_issues"])

    @pytest.mark.asyncio
    async def test_round_trip_export_import(self):
        """A skill exported from one environment can be imported into another."""
        # Create and export
        registry = get_skill_registry()
        spec = SkillSpec(
            id="",
            name="Round Trip Skill",
            description="Testing round-trip",
            version="1.0.0",
            agents=["a1"],
            tools=["file_reader"],
            workflow={"type": "dag", "nodes": [], "edges": []},
            tags=["round-trip"],
        )
        create_result = await registry.create_skill(spec)
        zip_bytes, _ = await export_skill_to_zip(create_result["skill_id"])

        # Import into a new skill
        import_result = await import_skill_from_zip(zip_bytes, install=True)

        assert import_result["valid"]
        assert import_result["installed"]
        assert import_result["skill_id"] != create_result["skill_id"]  # New ID

        # Verify the imported skill
        imported_skill = await registry.get_skill(import_result["skill_id"])
        assert imported_skill is not None
        assert imported_skill["name"] == "Round Trip Skill"