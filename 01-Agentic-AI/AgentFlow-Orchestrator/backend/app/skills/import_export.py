"""Skill import/export — packages skills as .skill.zip and imports them.

Matches instruction.md section 28 (Skill Import) and Phase 8 acceptance:
"A skill exported from one environment can be imported into another."

Export pipeline:
  Skill from DB → YAML manifest → .skill.zip → download

Import pipeline (from instruction.md §28):
  Upload → Extract → Validate → Security Scan → Dependency Check
  → Preview → User Approval → Install

Never execute an uploaded skill before validation.
"""

import io
import json
import logging
import os
import tempfile
import zipfile
from typing import Any

import yaml

from app.models.skill_schema import SkillSpec
from app.skills.registry import SkillRegistry, get_skill_registry
from app.skills.yaml_parser import (
    SkillValidationError,
    parse_agent_specs_from_yaml,
    parse_skill_yaml,
    validate_skill,
    yaml_to_skill_spec,
)

logger = logging.getLogger(__name__)


class SkillImportError(Exception):
    """Raised when skill import fails."""


class SkillExportError(Exception):
    """Raised when skill export fails."""


# --- Export ---


def skill_spec_to_yaml(spec: SkillSpec, agent_data: list[dict] | None = None) -> str:
    """Convert a SkillSpec to a YAML string.

    Args:
        spec: The SkillSpec to convert.
        agent_data: Optional full agent definitions to include.

    Returns:
        YAML string.
    """
    data: dict[str, Any] = {
        "name": spec.name,
        "version": spec.version,
        "description": spec.description,
    }

    if spec.author:
        data["author"] = spec.author
    if spec.tags:
        data["tags"] = spec.tags

    # Inputs/outputs
    if spec.inputs:
        data["inputs"] = [{"name": k, **v} for k, v in spec.inputs.items()]
    if spec.outputs:
        data["outputs"] = [{"name": k, **v} for k, v in spec.outputs.items()]

    # Agents — use full definitions if available, otherwise just IDs
    if agent_data:
        data["agents"] = agent_data
    else:
        data["agents"] = spec.agents

    # Tools
    if spec.tools:
        data["tools"] = spec.tools

    # Workflow
    if spec.workflow:
        data["workflow"] = spec.workflow

    # Evaluation
    if spec.evaluation:
        data["evaluation"] = spec.evaluation

    # Permissions
    if spec.permissions:
        data["permissions"] = spec.permissions

    data["enabled"] = spec.enabled

    return yaml.dump(data, default_flow_style=False, sort_keys=False)


async def export_skill_to_zip(skill_id: str) -> tuple[bytes, str]:
    """Export a skill as a .skill.zip archive.

    The archive contains:
    - skill.yaml (the skill manifest)
    - README.md (auto-generated)
    - spec.json (full spec data for round-trip import)

    Args:
        skill_id: The skill to export.

    Returns:
        Tuple of (zip_bytes, filename).

    Raises:
        SkillExportError: If the skill doesn't exist or has no active version.
    """
    registry = get_skill_registry()
    skill_data = await registry.get_skill(skill_id)
    if skill_data is None:
        raise SkillExportError(f"Skill '{skill_id}' not found")

    active_version = skill_data.get("active_version")
    if active_version is None:
        raise SkillExportError(f"Skill '{skill_id}' has no active version")

    spec_data = active_version.get("spec_data", {})

    # Reconstruct SkillSpec
    try:
        spec = SkillSpec(**spec_data)
    except Exception as e:
        raise SkillExportError(f"Failed to reconstruct skill spec: {e}")

    # Extract agent definitions from spec_data (if present)
    agent_data = spec_data.get("agents", [])

    # Generate YAML manifest
    yaml_content = skill_spec_to_yaml(spec, agent_data if agent_data else None)

    # Generate README
    readme = _generate_readme(skill_data, spec)

    # Create zip in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("skill.yaml", yaml_content)
        zf.writestr("README.md", readme)
        zf.writestr("spec.json", json.dumps(spec_data, indent=2))

    filename = f"{spec.name.replace(' ', '_').lower()}.skill.zip"

    logger.info(f"Exported skill '{skill_id}' as {filename}")
    return buf.getvalue(), filename


def _generate_readme(skill_data: dict, spec: SkillSpec) -> str:
    """Generate a README.md for the skill package."""
    lines = [
        f"# {spec.name}",
        "",
        f"**Version:** {spec.version}",
        f"**Description:** {spec.description}",
        "",
    ]

    if spec.author:
        lines.append(f"**Author:** {spec.author}")
    if spec.tags:
        lines.append(f"**Tags:** {', '.join(spec.tags)}")

    lines.extend([
        "",
        "## Agents",
        "",
    ])
    for agent_id in spec.agents:
        lines.append(f"- {agent_id}")

    if spec.tools:
        lines.extend([
            "",
            "## Tools",
            "",
        ])
        for tool_id in spec.tools:
            lines.append(f"- {tool_id}")

    lines.extend([
        "",
        "## Usage",
        "",
        "Import this skill via the AgentOS API:",
        "```bash",
        f"curl -X POST http://localhost:8000/api/skills/upload -F 'file=@{spec.name}.skill.zip'",
        "```",
        "",
        "Generated by AgentOS Skill Export",
    ])

    return "\n".join(lines)


# --- Import ---


async def import_skill_from_zip(
    zip_bytes: bytes,
    install: bool = True,
    check_tools: bool = True,
) -> dict[str, Any]:
    """Import a skill from a .skill.zip archive.

    Import pipeline (from instruction.md §28):
    1. Extract — unzip and read skill.yaml
    2. Validate — check required fields, tools, agents
    3. Security Scan — check for dangerous patterns
    4. Dependency Check — verify tools exist in registry
    5. Preview — return validation results
    6. Install — save to registry (if install=True)

    Never executes the skill — only validates and installs.

    Args:
        zip_bytes: The .skill.zip file content.
        install: If True, install the skill after validation.
        check_tools: If True, verify tools exist in the registry.

    Returns:
        Dict with validation results and (if installed) skill info.

    Raises:
        SkillImportError: If extraction or validation fails.
    """
    # Step 1: Extract
    try:
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            file_list = zf.namelist()

            if "skill.yaml" not in file_list:
                raise SkillImportError("Archive must contain skill.yaml")

            yaml_content = zf.read("skill.yaml").decode("utf-8")

            # Try to read spec.json for full agent definitions
            spec_json_data: dict[str, Any] = {}
            if "spec.json" in file_list:
                try:
                    spec_json_data = json.loads(zf.read("spec.json"))
                except json.JSONDecodeError:
                    pass  # Non-critical — YAML is the primary source
    except zipfile.BadZipFile:
        raise SkillImportError("Invalid zip file")
    except Exception as e:
        raise SkillImportError(f"Extraction failed: {e}")

    # Step 2: Parse YAML
    try:
        yaml_data = parse_skill_yaml(yaml_content)
    except SkillValidationError as e:
        raise SkillImportError(f"YAML parsing failed: {e.errors}")

    # Convert to SkillSpec
    try:
        spec = yaml_to_skill_spec(yaml_data)
    except SkillValidationError as e:
        raise SkillImportError(f"Skill spec conversion failed: {e.errors}")

    # Extract full agent specs (for validation and storage)
    agent_specs = parse_agent_specs_from_yaml(yaml_data)

    # Step 3: Security Scan
    security_issues = _security_scan(yaml_data, yaml_content)
    if security_issues:
        raise SkillImportError(f"Security scan failed: {security_issues}")

    # Step 4: Validate + Dependency Check
    validation_issues = validate_skill(spec, agent_specs, check_tools=check_tools)
    if validation_issues:
        return {
            "valid": False,
            "spec": spec.model_dump(),
            "validation_issues": validation_issues,
            "installed": False,
        }

    # Step 5: Preview (return validation result)
    if not install:
        return {
            "valid": True,
            "spec": spec.model_dump(),
            "agent_count": len(agent_specs),
            "validation_issues": [],
            "installed": False,
        }

    # Step 6: Install
    # Store full agent definitions in spec_data for round-trip
    # SkillSpec.agents is list[str] (agent IDs), but we also store full agent
    # definitions in a separate "agent_definitions" key for execution
    spec_data = spec.model_dump()
    if agent_specs:
        spec_data["agent_definitions"] = [a.model_dump() for a in agent_specs]

    # Create a SkillSpec (agents field stays as string IDs)
    install_spec = SkillSpec(**spec_data)

    registry = get_skill_registry()
    try:
        result = await registry.create_skill(install_spec, author=spec.author)
    except Exception as e:
        raise SkillImportError(f"Installation failed: {e}")

    logger.info(
        f"Imported skill '{spec.name}' (id={result['skill_id']}, "
        f"version={result['version']}, agents={len(agent_specs)})"
    )

    return {
        "valid": True,
        "spec": spec.model_dump(),
        "agent_count": len(agent_specs),
        "validation_issues": [],
        "installed": True,
        "skill_id": result["skill_id"],
        "version": result["version"],
    }


def _security_scan(yaml_data: dict[str, Any], yaml_content: str) -> list[str]:
    """Scan skill YAML for dangerous patterns.

    Checks for:
    - Shell commands in agent goals/prompts
    - File system destructive operations
    - Network operations without permission

    Returns:
        List of security issues (empty = safe).
    """
    issues: list[str] = []

    # Check for dangerous patterns in YAML content
    dangerous_patterns = [
        ("rm -rf", "Destructive shell command detected"),
        ("os.system", "Direct OS command execution detected"),
        ("subprocess.call", "Subprocess execution detected"),
        ("eval(", "Code evaluation detected"),
        ("exec(", "Code execution detected"),
    ]

    yaml_lower = yaml_content.lower()
    for pattern, message in dangerous_patterns:
        if pattern.lower() in yaml_lower:
            issues.append(message)

    # Check permissions for network access without flagging
    permissions = yaml_data.get("permissions", {})
    if isinstance(permissions, dict):
        has_network = permissions.get("network", False)
        tools = yaml_data.get("tools", [])
        if isinstance(tools, list):
            for tool_id in tools:
                if tool_id in ("http_request", "web_search") and not has_network:
                    issues.append(
                        f"Tool '{tool_id}' requires network access but "
                        "permissions.network is not set to true"
                    )

    return issues