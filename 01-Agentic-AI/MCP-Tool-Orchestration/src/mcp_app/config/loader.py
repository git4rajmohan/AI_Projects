"""YAML config loader with strict schema validation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from mcp_app.config.schema import AppSettings, MCPServersConfig, PoliciesConfig
from mcp_app.core.errors import ConfigError

# Default config directory: ../../../../config relative to loader.py
# loader.py lives at src/mcp_app/config/loader.py → 4 parents = project root (mcp_app/)
_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"

# Maps env var names (from .env.llm) to nested paths in the raw settings dict.
# Tuple: (section_key, field_key). Use None section for top-level keys.
_LLM_ENV_OVERRIDES: dict[str, tuple[Optional[str], str]] = {
    "OPENAI_COMPAT_API_KEY":     ("openai_compat", "api_key"),
    "OPENAI_COMPAT_BASE_URL":    ("openai_compat", "base_url"),
    "OPENAI_COMPAT_MODEL":       ("openai_compat", "model"),
    "OPENAI_COMPAT_TEMPERATURE": ("openai_compat", "temperature"),
    "OLLAMA_HOST":               ("ollama", "host"),
    "OLLAMA_MODEL":              ("ollama", "model"),
    "OLLAMA_API_KEY":            ("ollama", "api_key"),
    "OLLAMA_TEMPERATURE":        ("ollama", "temperature"),
    "OLLAMA_NUM_CTX":            ("ollama", "num_ctx"),
    "LLM_PROVIDER":              (None, "llm_provider"),
    "VISION_ENABLED":            ("vision", "enabled"),
    "VISION_PROVIDER":           ("vision", "provider"),
    "VISION_BASE_URL":           ("vision", "base_url"),
    "VISION_API_KEY":            ("vision", "api_key"),
    "VISION_MODEL":              ("vision", "model"),
    "VISION_TEMPERATURE":        ("vision", "temperature"),
}


def _find_config_dir(override: Optional[Path] = None) -> Path:
    """Resolve the config directory, checking env var then default."""
    if override:
        return override
    env_dir = os.environ.get("MCP_APP_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_CONFIG_DIR


def _load_yaml(path: Path) -> dict:
    """Load a YAML file and return dict (empty dict if file missing)."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _apply_llm_env_file(raw: dict, env_file: Path) -> None:
    """Parse .env.llm and overlay values onto the raw settings dict."""
    if not env_file.is_file():
        return
    env_vars: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env_vars[k.strip()] = v.strip()
    for env_key, (section, field) in _LLM_ENV_OVERRIDES.items():
        if env_key not in env_vars:
            continue
        if section is None:
            raw[field] = env_vars[env_key]
        else:
            raw.setdefault(section, {})[field] = env_vars[env_key]


def load_app_settings(config_dir: Optional[Path] = None) -> AppSettings:
    """Load and validate app_settings.yaml, applying .env.llm overrides if present."""
    config_dir = _find_config_dir(config_dir)
    raw = _load_yaml(config_dir / "app_settings.yaml")
    # config_dir is mcp_app/config/ — parent is mcp_app/
    _apply_llm_env_file(raw, config_dir.parent / ".env.llm")
    try:
        return AppSettings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(
            f"Invalid app_settings.yaml:\n{_format_validation_error(exc)}"
        ) from exc


def load_policies(config_dir: Optional[Path] = None) -> PoliciesConfig:
    """Load and validate policies.yaml."""
    config_dir = _find_config_dir(config_dir)
    raw = _load_yaml(config_dir / "policies.yaml")
    try:
        return PoliciesConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(
            f"Invalid policies.yaml:\n{_format_validation_error(exc)}"
        ) from exc


def load_servers(config_dir: Optional[Path] = None) -> MCPServersConfig:
    """Load and validate mcp_servers.yaml."""
    config_dir = _find_config_dir(config_dir)
    raw = _load_yaml(config_dir / "mcp_servers.yaml")
    try:
        return MCPServersConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(
            f"Invalid mcp_servers.yaml:\n{_format_validation_error(exc)}"
        ) from exc


def load_all_configs(
    config_dir: Optional[Path] = None,
) -> tuple[AppSettings, PoliciesConfig, MCPServersConfig]:
    """
    Load all three config files in one call.

    Returns:
        (app_settings, policies, servers_config)

    Raises:
        ConfigError on any validation failure.
    """
    cd = _find_config_dir(config_dir)
    settings = load_app_settings(cd)
    policies = load_policies(cd)
    servers = load_servers(cd)
    return settings, policies, servers


def _format_validation_error(exc: ValidationError) -> str:
    """Produce a human-readable summary of pydantic validation errors."""
    lines: list[str] = []
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err["loc"])
        lines.append(f"  [{loc}] {err['msg']}")
    return "\n".join(lines)
