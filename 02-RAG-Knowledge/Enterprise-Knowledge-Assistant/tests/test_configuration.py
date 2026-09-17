"""Tests for the configuration layer (`app.config.settings`).

Covers the two cases required by plan.md Phase 2:
- ``test_configuration_loading``  — reads a temporary `.env` file.
- ``test_default_configuration``  — defaults applied when env vars are absent.

All tests are hermetic: they pass explicit ``environ``/``env_file`` mappings to
``Settings.from_env`` and never read (or mutate) the real process environment,
so they also pass with no local services running and regardless of the real
project `.env` contents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import (
    ConfigurationError,
    PROJECT_ROOT,
    Settings,
)


def _minimal_cloud_env(tmp_path: Path) -> dict[str, str]:
    """A complete, valid cloud-provider env mapping (paths point at tmp)."""
    return {
        "OLLAMA_PROVIDER": "cloud",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_CLOUD_BASE_URL": "https://ollama.com/api",
        "OLLAMA_API_KEY": "test-key-not-real",
        "OLLAMA_LLM_MODEL": "gpt-oss:120b",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text",
        "QDRANT_URL": "http://localhost:6333",
        "QDRANT_COLLECTION": "enterprise_documents",
        "QDRANT_API_KEY": "",
        "TOP_K": "7",
        "CHUNK_SIZE": "512",
        "CHUNK_OVERLAP": "64",
        "DATA_DIR": str(tmp_path / "data"),
        "DOCUMENT_DIR": str(tmp_path / "data" / "documents"),
        "METADATA_DIR": str(tmp_path / "data" / "metadata"),
        "LOG_LEVEL": "INFO",
    }


# --------------------------------------------------------------------------- #
# 1. Loading a .env file                                                      #
# --------------------------------------------------------------------------- #
def test_configuration_loading(tmp_path: Path) -> None:
    """Settings reads every documented key from a temporary .env file."""
    env_path = tmp_path / ".env"
    lines = [f"{key}={value}" for key, value in _minimal_cloud_env(tmp_path).items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    settings = Settings.from_env(env_file=env_path)

    assert settings.provider == "cloud"
    assert settings.is_cloud_provider is True
    assert settings.local_base_url == "http://localhost:11434"
    assert settings.cloud_base_url == "https://ollama.com/api"
    assert settings.api_key == "test-key-not-real"
    assert settings.llm_model == "gpt-oss:120b"
    assert settings.embed_model == "nomic-embed-text"
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_collection == "enterprise_documents"
    assert settings.top_k == 7  # int conversion applied
    assert settings.chunk_size == 512
    assert settings.chunk_overlap == 64
    # Absolute paths given in .env are honored as-is (resolved).
    assert settings.data_dir == (tmp_path / "data").resolve()
    assert settings.document_dir == (tmp_path / "data" / "documents").resolve()
    assert settings.metadata_dir == (tmp_path / "data" / "metadata").resolve()
    assert settings.log_level == "INFO"


def test_configuration_loading_relative_paths_resolve(tmp_path: Path) -> None:
    """Relative path values join the project root and are resolved absolute."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_PROVIDER=local",
                "DATA_DIR=./data",
                "DOCUMENT_DIR=./data/documents",
                "METADATA_DIR=./data/metadata",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings.from_env(env_file=env_path)

    assert settings.data_dir == (PROJECT_ROOT / "data").resolve()
    assert settings.document_dir == (PROJECT_ROOT / "data" / "documents").resolve()
    assert settings.metadata_dir == (PROJECT_ROOT / "data" / "metadata").resolve()


def test_configuration_loading_blank_value_means_unset(tmp_path: Path) -> None:
    """A blank value falls back to the default (not an empty string)."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_PROVIDER=local",
                "OLLAMA_LLM_MODEL=",  # blank -> default
                "TOP_K=   ",  # whitespace -> default
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings.from_env(env_file=env_path)

    assert settings.llm_model == "qwen3:8b"
    assert settings.top_k == 5


# --------------------------------------------------------------------------- #
# 2. Defaults when env vars are absent                                        #
# --------------------------------------------------------------------------- #
def test_default_configuration() -> None:
    """With an empty mapping, defaults (instructions.md examples) apply."""
    settings = Settings.from_env(environ={})

    assert settings.provider == "local"
    assert settings.is_cloud_provider is False
    assert settings.local_base_url == "http://localhost:11434"
    assert settings.cloud_base_url == "https://ollama.com/api"
    assert settings.llm_model == "qwen3:8b"
    assert settings.embed_model == "nomic-embed-text"
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_collection == "enterprise_documents"
    assert settings.top_k == 5
    assert settings.chunk_size == 800
    assert settings.chunk_overlap == 100
    assert settings.data_dir == (PROJECT_ROOT / "data").resolve()
    assert settings.document_dir == (PROJECT_ROOT / "data" / "documents").resolve()
    assert settings.metadata_dir == (PROJECT_ROOT / "data" / "metadata").resolve()
    assert settings.log_level == "INFO"


# --------------------------------------------------------------------------- #
# 3. Validation errors                                                        #
# --------------------------------------------------------------------------- #
def test_cloud_provider_requires_real_api_key() -> None:
    """OLLAMA_PROVIDER=cloud rejects placeholder/missing keys."""
    base = _minimal_cloud_env(Path("."))
    for bad in ("", "<your-ollama-api-key>"):
        env = {**base, "OLLAMA_API_KEY": bad}
        with pytest.raises(ConfigurationError, match="OLLAMA_API_KEY"):
            Settings.from_env(environ=env)


def test_invalid_provider_rejected() -> None:
    base = _minimal_cloud_env(Path("."))
    env = {**base, "OLLAMA_PROVIDER": "openai"}
    with pytest.raises(ConfigurationError, match="OLLAMA_PROVIDER"):
        Settings.from_env(environ=env)


def test_non_integer_top_k_rejected() -> None:
    base = _minimal_cloud_env(Path("."))
    env = {**base, "TOP_K": "five"}
    with pytest.raises(ConfigurationError, match="TOP_K"):
        Settings.from_env(environ=env)


def test_chunk_overlap_must_be_less_than_chunk_size() -> None:
    base = _minimal_cloud_env(Path("."))
    env = {**base, "CHUNK_SIZE": "100", "CHUNK_OVERLAP": "100"}
    with pytest.raises(ConfigurationError, match="CHUNK_OVERLAP"):
        Settings.from_env(environ=env)


def test_invalid_log_level_rejected() -> None:
    base = _minimal_cloud_env(Path("."))
    env = {**base, "LOG_LEVEL": "VERBOSE"}
    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        Settings.from_env(environ=env)