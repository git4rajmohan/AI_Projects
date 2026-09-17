"""Tests for skill YAML parsing and validation.

Matches instruction.md section 29 (Skill YAML Format) and section 30 (Skill Validation).
"""

import pytest

from app.skills.yaml_parser import (
    SkillValidationError,
    parse_agent_specs_from_yaml,
    parse_skill_yaml,
    validate_skill,
    yaml_to_skill_spec,
)
from app.models.skill_schema import SkillSpec


VALID_YAML = """
name: test-skill
version: 1.0.0
description: A test skill for validation

author: Tester
tags:
  - test
  - validation

inputs:
  - name: input_file
    type: file

outputs:
  - name: result
    type: text

agents:
  - id: processor
    name: Processor
    description: Processes the input
    goal: Process input and produce output
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
    - id: processor
  edges: []

evaluation:
  criteria:
    - accuracy
    - completeness
  threshold: 0.7

permissions:
  file_read: true
  file_write: false
  network: false

enabled: true
"""


class TestParseSkillYaml:
    """Test YAML parsing."""

    def test_parse_valid_yaml(self):
        """Valid YAML parses into a dict."""
        data = parse_skill_yaml(VALID_YAML)
        assert data["name"] == "test-skill"
        assert data["version"] == "1.0.0"
        assert "agents" in data

    def test_parse_invalid_yaml(self):
        """Invalid YAML raises SkillValidationError."""
        with pytest.raises(SkillValidationError):
            parse_skill_yaml("name: [unclosed")

    def test_parse_non_dict_yaml(self):
        """Non-dict YAML (e.g., a list) raises error."""
        with pytest.raises(SkillValidationError):
            parse_skill_yaml("- item1\n- item2")


class TestYamlToSkillSpec:
    """Test YAML to SkillSpec conversion."""

    def test_valid_conversion(self):
        """Valid YAML converts to SkillSpec."""
        data = parse_skill_yaml(VALID_YAML)
        spec = yaml_to_skill_spec(data)

        assert spec.name == "test-skill"
        assert spec.version == "1.0.0"
        assert "test" in spec.tags
        assert "processor" in spec.agents
        assert "file_reader" in spec.tools
        assert spec.workflow["type"] == "dag"

    def test_missing_name_raises(self):
        """Missing name raises validation error."""
        data = {"version": "1.0.0", "description": "test", "agents": ["a1"]}
        with pytest.raises(SkillValidationError):
            yaml_to_skill_spec(data)

    def test_missing_description_raises(self):
        """Missing description raises validation error."""
        data = {"name": "test", "version": "1.0.0", "agents": ["a1"]}
        with pytest.raises(SkillValidationError):
            yaml_to_skill_spec(data)

    def test_invalid_version_raises(self):
        """Invalid version format raises error."""
        data = {"name": "test", "description": "test", "version": "abc", "agents": ["a1"]}
        with pytest.raises(SkillValidationError):
            yaml_to_skill_spec(data)

    def test_invalid_workflow_type_raises(self):
        """Invalid workflow type raises error."""
        data = parse_skill_yaml(VALID_YAML)
        data["workflow"]["type"] = "invalid_type"
        with pytest.raises(SkillValidationError):
            yaml_to_skill_spec(data)

    def test_inputs_converted_to_dict(self):
        """Inputs list is converted to dict keyed by name."""
        data = parse_skill_yaml(VALID_YAML)
        spec = yaml_to_skill_spec(data)

        assert "input_file" in spec.inputs
        assert spec.inputs["input_file"]["type"] == "file"


class TestParseAgentSpecs:
    """Test parsing full agent specs from YAML."""

    def test_parse_agent_specs(self):
        """Full agent definitions are parsed into AgentSpecs."""
        data = parse_skill_yaml(VALID_YAML)
        specs = parse_agent_specs_from_yaml(data)

        assert len(specs) == 1
        assert specs[0].id == "processor"
        assert specs[0].name == "Processor"
        assert "file_reader" in specs[0].tools

    def test_string_agents_return_empty(self):
        """When agents are just string IDs, no AgentSpecs are returned."""
        data = {"agents": ["agent_a", "agent_b"]}
        specs = parse_agent_specs_from_yaml(data)
        assert specs == []


class TestValidateSkill:
    """Test skill validation."""

    def test_valid_skill_no_issues(self):
        """A valid skill has no validation issues."""
        data = parse_skill_yaml(VALID_YAML)
        spec = yaml_to_skill_spec(data)
        agent_specs = parse_agent_specs_from_yaml(data)

        issues = validate_skill(spec, agent_specs, check_tools=True)
        assert issues == []

    def test_missing_agents_flagged(self):
        """Skill with no agents is flagged."""
        spec = SkillSpec(
            id="",
            name="test",
            description="test",
            version="1.0.0",
            agents=[],
        )
        issues = validate_skill(spec, check_tools=False)
        assert any("at least one agent" in i for i in issues)

    def test_unknown_tool_flagged(self):
        """Unknown tool is flagged when check_tools=True."""
        spec = SkillSpec(
            id="",
            name="test",
            description="test",
            version="1.0.0",
            agents=["a1"],
            tools=["nonexistent_tool"],
        )
        issues = validate_skill(spec, check_tools=True)
        assert any("nonexistent_tool" in i for i in issues)

    def test_invalid_version_flagged(self):
        """Invalid version is flagged."""
        spec = SkillSpec(
            id="",
            name="test",
            description="test",
            version="invalid",
            agents=["a1"],
        )
        issues = validate_skill(spec, check_tools=False)
        assert any("version" in i.lower() for i in issues)

    def test_duplicate_agent_ids_flagged(self):
        """Duplicate agent IDs are flagged."""
        from app.models.agent import AgentSpec

        spec = SkillSpec(
            id="",
            name="test",
            description="test",
            version="1.0.0",
            agents=["a1", "a1"],
        )
        agents = [
            AgentSpec(id="a1", name="A1", goal="G1"),
            AgentSpec(id="a1", name="A1", goal="G2"),
        ]
        issues = validate_skill(spec, agents, check_tools=False)
        assert any("duplicate" in i.lower() for i in issues)

    def test_missing_dependency_flagged(self):
        """Agent depending on non-existent agent is flagged."""
        from app.models.agent import AgentSpec

        spec = SkillSpec(
            id="",
            name="test",
            description="test",
            version="1.0.0",
            agents=["a1"],
        )
        agents = [AgentSpec(id="a1", name="A1", goal="G1", dependencies=["nonexistent"])]
        issues = validate_skill(spec, agents, check_tools=False)
        assert any("nonexistent" in i for i in issues)