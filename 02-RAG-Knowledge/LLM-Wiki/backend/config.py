"""
App configuration — load/save to config.json.
When packaged as exe, config.json is stored next to the executable.
When running from source, it's stored in the project root.
API keys live in config.json (gitignored) or in environment variables / .env
(see .env.example) — never in code. Explicit values win: config.json > .env.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


def _get_config_path() -> Path:
    """Return the config.json path — next to the exe when frozen, or project root when running from source."""
    if getattr(sys, "frozen", False):
        # PyInstaller / PyOxidizer — use the directory of the executable
        return Path(sys.executable).parent / "config.json"
    return Path(__file__).parent.parent / "config.json"


CONFIG_PATH = _get_config_path()

# Environment-variable fallbacks (loaded from .env too). Only fill EMPTY fields,
# so values typed in the UI / saved to config.json always take priority.
_ENV_OVERRIDES = {
    "provider": "LLMWIKI_PROVIDER",
    "model": "LLMWIKI_MODEL",
    "api_key": "LLMWIKI_API_KEY",
    "base_url": "LLMWIKI_BASE_URL",
    "azure_endpoint": "LLMWIKI_AZURE_ENDPOINT",
    "azure_deployment": "LLMWIKI_AZURE_DEPLOYMENT",
    "azure_api_version": "LLMWIKI_AZURE_API_VERSION",
}


def _load_env_file() -> None:
    """Load KEY=VALUE pairs from ./.env into os.environ (stdlib only, no python-dotenv).
    Never overrides variables already set in the environment. Ignores comments/blanks."""
    env_path = CONFIG_PATH.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def apply_env_fallback_to_llm(llm: "LLMConfig") -> "LLMConfig":
    """Fill empty LLMConfig fields from environment / .env (explicit values win)."""
    updates = {
        field: os.environ[var]
        for field, var in _ENV_OVERRIDES.items()
        if os.environ.get(var) and not getattr(llm, field)
    }
    return llm.model_copy(update=updates) if updates else llm


class LLMConfig(BaseModel):
    provider: str = "local-cpu"       # openai | azure | anthropic | ollama | lmstudio | together | baseten | local-cpu
    model: str = "gemma-2-2b-it"
    api_key: str = ""
    base_url: str = ""                # used for ollama, lmstudio, together, baseten
    azure_endpoint: str = ""          # azure only
    azure_deployment: str = ""        # azure only
    azure_api_version: str = "2024-02-01"
    temperature: float = 0.3
    max_tokens: int = 4000
    llm_connected: bool = False       # only True after a successful Test Connection


class WikiProject(BaseModel):
    id: str
    name: str
    root_path: str                    # absolute path to wiki project root folder


class AppConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    projects: List[WikiProject] = []
    active_project_id: Optional[str] = None


def load_config() -> AppConfig:
    _load_env_file()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            llm = apply_env_fallback_to_llm(LLMConfig(**data.get("llm", {})))
            return AppConfig(
                llm=llm,
                projects=data.get("projects", []),
                active_project_id=data.get("active_project_id"),
            )
        except Exception:
            pass
    return AppConfig(llm=apply_env_fallback_to_llm(LLMConfig()))


def save_config(cfg: AppConfig) -> None:
    data = json.loads(cfg.model_dump_json())
    # Never persist an env-provided secret into config.json — it stays in .env only.
    env_key = os.environ.get("LLMWIKI_API_KEY", "")
    if env_key and data["llm"]["api_key"] == env_key:
        data["llm"]["api_key"] = ""
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def masked_config(cfg: AppConfig) -> dict:
    """Return config dict with API keys masked for safe frontend delivery."""
    data = cfg.model_dump()
    if data["llm"]["api_key"]:
        data["llm"]["api_key"] = "***"
    data["llm"]["is_configured"] = is_llm_configured(cfg.llm)
    # Include local model catalog and download status
    from backend.services import local_model_service
    data["llm"]["local_model_downloaded"] = local_model_service.is_model_downloaded(
        cfg.llm.model if cfg.llm.provider == "local-cpu" else None
    )
    data["llm"]["local_models_available"] = [
        {
            "id": m["id"],
            "label": m["label"],
            "size": m["size"],
            "downloaded": True,
        }
        for m in local_model_service.AVAILABLE_MODELS
        if local_model_service.is_model_downloaded(m["id"])
    ]
    return data


def is_llm_configured(llm: LLMConfig) -> bool:
    """Return True only if the user has successfully tested the LLM connection."""
    return llm.llm_connected
