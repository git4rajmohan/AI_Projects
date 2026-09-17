"""Central configuration for the Enterprise Knowledge Assistant.

Every setting is read from environment variables (`.env` at the project root,
loaded via python-dotenv). No model names, URLs or file paths are hard-coded
in application code — the example values from `instructions.md` are used only
as *defaults* for when an environment variable is absent or blank.

Each `.env` key documented in `.env.example` maps to exactly one typed field:

    OLLAMA_PROVIDER        -> provider          ("local" | "cloud")
    OLLAMA_BASE_URL        -> local_base_url    (local Ollama daemon)
    OLLAMA_CLOUD_BASE_URL  -> cloud_base_url    (native Ollama cloud API)
    OLLAMA_API_KEY         -> api_key           (real key only in .env)
    OLLAMA_LLM_MODEL       -> llm_model
    OLLAMA_EMBED_MODEL     -> embed_model
    QDRANT_URL             -> qdrant_url
    QDRANT_COLLECTION      -> qdrant_collection
    QDRANT_API_KEY         -> qdrant_api_key
    TOP_K                  -> top_k
    CHUNK_SIZE             -> chunk_size
    CHUNK_OVERLAP          -> chunk_overlap
    DATA_DIR               -> data_dir
    DOCUMENT_DIR           -> document_dir
    METADATA_DIR           -> metadata_dir
    LOG_LEVEL              -> log_level
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values, load_dotenv

#: Absolute path of the project root (two levels above this file:
#: app/config/settings.py -> app/config -> app -> project root).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigurationError(ValueError):
    """Raised when .env values are missing or invalid for the selected mode."""


@dataclass(frozen=True)
class Settings:
    """Typed view of all `.env` configuration for the application."""

    # --- LLM provider selection ---
    provider: str = "local"
    # --- Ollama endpoints (local daemon / cloud native API) ---
    local_base_url: str = "http://localhost:11434"
    cloud_base_url: str = "https://ollama.com/api"
    api_key: str = ""
    # --- Models (defaults are instructions.md examples, not decisions) ---
    llm_model: str = "qwen3:8b"
    embed_model: str = "nomic-embed-text"
    # --- Qdrant ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "enterprise_documents"
    qdrant_api_key: str = ""
    # --- Retrieval / chunking ---
    top_k: int = 5
    chunk_size: int = 800
    chunk_overlap: int = 100
    # --- Paths (resolved to absolute, relative values join PROJECT_ROOT) ---
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    document_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "documents")
    metadata_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "metadata")
    # --- Logging ---
    log_level: str = "INFO"

    # ------------------------------------------------------------------ #
    # Construction                                                       #
    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(
        cls,
        *,
        env_file: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        """Build :class:`Settings` from environment values.

        Three modes, in order of precedence:

        1. ``environ`` given -> read strictly from that mapping (no side
           effects on the process environment). Useful for tests.
        2. ``env_file`` given (and no ``environ``) -> read strictly from that
           dotenv file, also without touching the process environment.
        3. neither given -> the production path: load the project `.env` into
           the process environment via ``load_dotenv`` (so downstream
           libraries can also see the values) and read ``os.environ``.
        """
        if environ is None and env_file is not None:
            raw = dotenv_values(env_file)
            environ = {k: (v if v is not None else "") for k, v in raw.items()}
        if environ is None:
            load_dotenv(PROJECT_ROOT / ".env")
            environ = os.environ
        return cls._from_mapping(environ)

    @classmethod
    def _from_mapping(cls, mapping: Mapping[str, str]) -> "Settings":
        def get(key: str, default: str) -> str:
            """Env value, treating a missing or blank value as unset."""
            value = mapping.get(key)
            if value is None or str(value).strip() == "":
                return default
            return str(value)

        def get_int(key: str, default: int) -> int:
            raw = get(key, str(default))
            try:
                return int(raw)
            except ValueError as exc:
                raise ConfigurationError(
                    f"{key} must be an integer, got {raw!r}"
                ) from exc

        def get_path(key: str, default: Path) -> Path:
            raw = get(key, str(default))
            path = Path(raw)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            return path.resolve()

        settings = cls(
            provider=get("OLLAMA_PROVIDER", "local").strip().lower(),
            local_base_url=get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            cloud_base_url=get("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api").rstrip("/"),
            api_key=get("OLLAMA_API_KEY", ""),
            llm_model=get("OLLAMA_LLM_MODEL", "qwen3:8b"),
            embed_model=get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            qdrant_url=get("QDRANT_URL", "http://localhost:6333").rstrip("/"),
            qdrant_collection=get("QDRANT_COLLECTION", "enterprise_documents"),
            qdrant_api_key=get("QDRANT_API_KEY", ""),
            top_k=get_int("TOP_K", 5),
            chunk_size=get_int("CHUNK_SIZE", 800),
            chunk_overlap=get_int("CHUNK_OVERLAP", 100),
            data_dir=get_path("DATA_DIR", PROJECT_ROOT / "data"),
            document_dir=get_path("DOCUMENT_DIR", PROJECT_ROOT / "data" / "documents"),
            metadata_dir=get_path("METADATA_DIR", PROJECT_ROOT / "data" / "metadata"),
            log_level=get("LOG_LEVEL", "INFO").strip().upper(),
        )
        settings.validate()
        return settings

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        """Raise :class:`ConfigurationError` on missing/invalid combinations.

        Called automatically by :meth:`from_env`; safe to call again after
        manually constructing a :class:`Settings` instance.
        """
        if self.provider not in ("local", "cloud"):
            raise ConfigurationError(
                f"OLLAMA_PROVIDER must be 'local' or 'cloud', got {self.provider!r}"
            )
        for name, value in (
            ("OLLAMA_BASE_URL", self.local_base_url),
            ("OLLAMA_CLOUD_BASE_URL", self.cloud_base_url),
            ("OLLAMA_LLM_MODEL", self.llm_model),
            ("OLLAMA_EMBED_MODEL", self.embed_model),
            ("QDRANT_URL", self.qdrant_url),
            ("QDRANT_COLLECTION", self.qdrant_collection),
        ):
            if not value:
                raise ConfigurationError(f"{name} must not be empty")

        if self.provider == "cloud" and (
            not self.api_key or self.api_key.startswith("<")
        ):
            raise ConfigurationError(
                "OLLAMA_PROVIDER=cloud requires a real OLLAMA_API_KEY in .env "
                "(placeholder values like '<your-ollama-api-key>' are rejected). "
                "Get a key at ollama.com/settings/keys."
            )

        if self.top_k < 1:
            raise ConfigurationError(f"TOP_K must be >= 1, got {self.top_k}")
        if self.chunk_size < 1:
            raise ConfigurationError(f"CHUNK_SIZE must be >= 1, got {self.chunk_size}")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ConfigurationError(
                "CHUNK_OVERLAP must satisfy 0 <= CHUNK_OVERLAP < CHUNK_SIZE "
                f"(got CHUNK_SIZE={self.chunk_size}, CHUNK_OVERLAP={self.chunk_overlap})"
            )
        if self.log_level not in _VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {self.log_level!r}"
            )

    # ------------------------------------------------------------------ #
    # Convenience                                                        #
    # ------------------------------------------------------------------ #
    @property
    def is_cloud_provider(self) -> bool:
        """True when the selected LLM provider is Ollama Cloud."""
        return self.provider == "cloud"


#: Process-wide settings singleton (real .env path). Tests build their own
#: Settings via ``from_env``; tests must call ``reset_settings`` if they
#: touch this singleton.
_settings: Settings | None = None


def get_settings() -> Settings:
    """Load once from the real `.env` and cache for the process lifetime."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
        _settings.validate()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings singleton (used by tests / after env changes)."""
    global _settings
    _settings = None