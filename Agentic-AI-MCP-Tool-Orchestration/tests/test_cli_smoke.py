"""CLI smoke tests for list-servers and list-tools (no real Ollama required)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from mcp_app.main import main

MOCK_SERVER = Path(__file__).parent / "mocks" / "mock_mcp_server" / "server.py"
PYTHON = sys.executable


# ── Helpers ─────────────────────────────────────────────────────────────────

def _write_configs(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()

    (cfg_dir / "app_settings.yaml").write_text(
        yaml.dump({
            "ollama": {"model": "test-model"},
            "logging": {"dir": str(tmp_path / "logs")},
        }),
        encoding="utf-8",
    )
    (cfg_dir / "policies.yaml").write_text(yaml.dump({}), encoding="utf-8")
    (cfg_dir / "mcp_servers.yaml").write_text(
        yaml.dump({
            "servers": [
                {
                    "id": "mock_srv",
                    "name": "Mock Server",
                    "enabled": True,
                    "transport": "stdio",
                    "stdio": {
                        "command": PYTHON,
                        "args": [str(MOCK_SERVER)],
                    },
                }
            ]
        }),
        encoding="utf-8",
    )
    return cfg_dir


# ── list-servers ──────────────────────────────────────────────────────────────

class TestListServers:
    def test_exits_zero(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "list-servers"]
        )
        assert result.exit_code == 0, result.output

    def test_shows_server_id(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "list-servers"]
        )
        assert "mock_srv" in result.output

    def test_shows_server_name(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "list-servers"]
        )
        assert "Mock Server" in result.output

    def test_empty_servers_no_crash(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "app_settings.yaml").write_text(
            yaml.dump({"logging": {"dir": str(tmp_path / "logs")}}), encoding="utf-8"
        )
        (cfg_dir / "policies.yaml").write_text(yaml.dump({}), encoding="utf-8")
        (cfg_dir / "mcp_servers.yaml").write_text(
            yaml.dump({"servers": []}), encoding="utf-8"
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--config-dir", str(cfg_dir), "list-servers"])
        assert result.exit_code == 0


# ── list-tools ────────────────────────────────────────────────────────────────

class TestListTools:
    def test_exits_zero(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "list-tools"]
        )
        assert result.exit_code == 0, result.output

    def test_shows_echo_tool(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "list-tools"]
        )
        assert "echo" in result.output

    def test_filter_by_server(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "list-tools", "--server", "mock_srv"]
        )
        assert result.exit_code == 0
        assert "echo" in result.output

    def test_filter_by_nonexistent_server_empty(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "list-tools", "--server", "ghost"]
        )
        assert result.exit_code == 0
        # Should say no tools available
        output_lower = result.output.lower()
        assert "no tools" in output_lower or result.output.strip() == ""


# ── health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_exits_zero(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "health"]
        )
        assert result.exit_code == 0, result.output

    def test_shows_server_id(self, tmp_path):
        cfg_dir = _write_configs(tmp_path)
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            main, ["--config-dir", str(cfg_dir), "health"]
        )
        assert "mock_srv" in result.output


# ── Config error ──────────────────────────────────────────────────────────────

class TestConfigError:
    def test_bad_config_exits_nonzero(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        # Write invalid app_settings
        (cfg_dir / "app_settings.yaml").write_text(
            yaml.dump({"tool_calling": {"mode": "invalid_mode"}}), encoding="utf-8"
        )
        (cfg_dir / "policies.yaml").write_text(yaml.dump({}), encoding="utf-8")
        (cfg_dir / "mcp_servers.yaml").write_text(
            yaml.dump({"servers": []}), encoding="utf-8"
        )
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--config-dir", str(cfg_dir), "list-servers"])
        assert result.exit_code != 0
