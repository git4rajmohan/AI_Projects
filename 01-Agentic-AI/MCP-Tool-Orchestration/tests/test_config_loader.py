"""Tests for config loading and validation failures."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from mcp_app.config.loader import load_app_settings, load_policies, load_servers, load_all_configs
from mcp_app.core.errors import ConfigError


# ── Helpers ───────────────────────────────────────────────────────────────────

def write_yaml(tmp_path: Path, filename: str, data: dict) -> Path:
    p = tmp_path / filename
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def make_config_dir(tmp_path: Path, **files) -> Path:
    """Create a temp config dir with optional yaml file overrides."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    for name, data in files.items():
        (cfg_dir / name).write_text(yaml.dump(data), encoding="utf-8")
    return cfg_dir


# ── AppSettings tests ─────────────────────────────────────────────────────────

class TestAppSettings:
    def test_defaults_when_file_empty(self, tmp_path):
        cfg_dir = make_config_dir(tmp_path)
        settings = load_app_settings(cfg_dir)
        assert settings.ollama.model == "qwen2.5:7b"
        assert settings.tool_calling.mode == "require_approval"
        assert settings.logging.level == "INFO"
        assert settings.limits.max_tool_output_chars == 20000
        assert settings.timeouts.llm_seconds == 60

    def test_custom_values(self, tmp_path):
        cfg_dir = make_config_dir(
            tmp_path,
            **{
                "app_settings.yaml": {
                    "ollama": {"model": "llama3:8b", "temperature": 0.5},
                    "tool_calling": {"mode": "auto"},
                    "logging": {"level": "DEBUG"},
                }
            },
        )
        settings = load_app_settings(cfg_dir)
        assert settings.ollama.model == "llama3:8b"
        assert settings.ollama.temperature == 0.5
        assert settings.tool_calling.mode == "auto"
        assert settings.logging.level == "DEBUG"

    def test_invalid_mode_raises(self, tmp_path):
        cfg_dir = make_config_dir(
            tmp_path,
            **{"app_settings.yaml": {"tool_calling": {"mode": "yolo"}}}
        )
        with pytest.raises(ConfigError, match="app_settings"):
            load_app_settings(cfg_dir)

    def test_invalid_log_level_raises(self, tmp_path):
        cfg_dir = make_config_dir(
            tmp_path,
            **{"app_settings.yaml": {"logging": {"level": "VERBOSE"}}}
        )
        with pytest.raises(ConfigError):
            load_app_settings(cfg_dir)


# ── Policies tests ────────────────────────────────────────────────────────────

class TestPolicies:
    def test_defaults(self, tmp_path):
        cfg_dir = make_config_dir(tmp_path)
        pol = load_policies(cfg_dir)
        assert pol.dangerous_tools_require_approval is True
        assert isinstance(pol.redact_keys, list)
        assert "token" in pol.redact_keys

    def test_custom_denied_tools(self, tmp_path):
        cfg_dir = make_config_dir(
            tmp_path,
            **{"policies.yaml": {"global_denied_tools": ["bad_tool"]}}
        )
        pol = load_policies(cfg_dir)
        assert "bad_tool" in pol.global_denied_tools

    def test_non_list_denied_raises(self, tmp_path):
        cfg_dir = make_config_dir(
            tmp_path,
            **{"policies.yaml": {"global_denied_tools": "bad_tool"}}
        )
        with pytest.raises(ConfigError):
            load_policies(cfg_dir)


# ── Server config tests ───────────────────────────────────────────────────────

class TestServerConfig:
    def _good_server(self):
        return {
            "servers": [
                {
                    "id": "test_srv",
                    "name": "Test Server",
                    "enabled": True,
                    "transport": "stdio",
                    "stdio": {"command": "python", "args": ["-m", "srv"]},
                }
            ]
        }

    def test_valid_server(self, tmp_path):
        cfg_dir = make_config_dir(tmp_path, **{"mcp_servers.yaml": self._good_server()})
        cfg = load_servers(cfg_dir)
        assert len(cfg.servers) == 1
        assert cfg.servers[0].id == "test_srv"

    def test_duplicate_id_raises(self, tmp_path):
        data = {
            "servers": [
                {"id": "dup", "name": "A", "enabled": True, "transport": "stdio",
                 "stdio": {"command": "py"}},
                {"id": "dup", "name": "B", "enabled": True, "transport": "stdio",
                 "stdio": {"command": "py"}},
            ]
        }
        cfg_dir = make_config_dir(tmp_path, **{"mcp_servers.yaml": data})
        with pytest.raises(ConfigError, match="[Dd]uplicate"):
            load_servers(cfg_dir)

    def test_missing_stdio_command_raises(self, tmp_path):
        data = {
            "servers": [
                {"id": "s1", "name": "X", "enabled": True, "transport": "stdio",
                 "stdio": {}}  # no command
            ]
        }
        cfg_dir = make_config_dir(tmp_path, **{"mcp_servers.yaml": data})
        with pytest.raises(ConfigError):
            load_servers(cfg_dir)

    def test_unknown_transport_raises(self, tmp_path):
        data = {
            "servers": [
                {"id": "s1", "name": "X", "enabled": True, "transport": "grpc"}
            ]
        }
        cfg_dir = make_config_dir(tmp_path, **{"mcp_servers.yaml": data})
        with pytest.raises(ConfigError):
            load_servers(cfg_dir)

    def test_disabled_server_ok(self, tmp_path):
        data = {
            "servers": [
                {"id": "s1", "name": "X", "enabled": False, "transport": "stdio",
                 "stdio": {"command": "py"}}
            ]
        }
        cfg_dir = make_config_dir(tmp_path, **{"mcp_servers.yaml": data})
        cfg = load_servers(cfg_dir)
        assert cfg.servers[0].enabled is False

    def test_empty_servers_list(self, tmp_path):
        cfg_dir = make_config_dir(tmp_path, **{"mcp_servers.yaml": {"servers": []}})
        cfg = load_servers(cfg_dir)
        assert cfg.servers == []

    def test_non_list_policy_raises(self, tmp_path):
        data = {
            "servers": [
                {
                    "id": "s1", "name": "X", "enabled": True, "transport": "stdio",
                    "stdio": {"command": "py"},
                    "policy": {"allowed_tools": "not_a_list"},
                }
            ]
        }
        cfg_dir = make_config_dir(tmp_path, **{"mcp_servers.yaml": data})
        with pytest.raises(ConfigError):
            load_servers(cfg_dir)

    def test_load_all_returns_tuple(self, tmp_path):
        cfg_dir = make_config_dir(tmp_path)
        settings, policies, servers = load_all_configs(cfg_dir)
        assert settings is not None
        assert policies is not None
        assert servers is not None
