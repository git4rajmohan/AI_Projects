"""Application configuration using pydantic-settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AgentOS application settings.

    All values can be overridden via environment variables or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENTOS_",
        extra="ignore",
    )

    # --- LLM ---
    llm_model: str = "openai/gpt-oss:120b"
    # OPENAI_API_KEY and OPENAI_API_BASE are read by LiteLLM directly from env

    # --- Database ---
    db_path: str = "data/agentos.db"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Security ---
    secret_key: str = "change-me-in-production"

    # --- Logging ---
    log_level: str = "INFO"

    # --- Execution Limits ---
    max_replans: int = 2
    max_execution_time_seconds: int = 3600
    max_total_tool_calls: int = 100

    @property
    def db_url(self) -> str:
        """Async SQLite database URL."""
        abs_path = Path(self.db_path).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{abs_path}"

    @property
    def db_url_sync(self) -> str:
        """Sync SQLite database URL (for ADK DatabaseSessionService)."""
        abs_path = Path(self.db_path).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{abs_path}"


# Singleton settings instance
settings = Settings()