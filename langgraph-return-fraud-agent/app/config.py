"""Application configuration loaded from environment variables (.env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All tunable knobs for the return agent service.

    Values are loaded from the `.env` file at the `return-agent/` root
    (or the process environment). Every field has a sane default so the
    service can run with zero configuration in tests.
    """

    # --- Ollama Cloud LLM -------------------------------------------------
    OLLAMA_API_KEY: str = ""
    OLLAMA_MODEL: str = "gpt-oss:120b"
    OLLAMA_BASE_URL: str = "https://ollama.com"

    # --- Persistence -------------------------------------------------------
    SQLITE_DB_PATH: str = "./checkpoints.sqlite"

    # --- Business thresholds (mirrors plan.md Decisions) --------------------
    HIGH_VALUE_THRESHOLD: float = 200.00   # refund > this => manager approval
    FRAUD_SCORE_THRESHOLD: float = 0.7     # fraud score >= this => manager approval
    MAX_PHOTO_RETRIES: int = 3             # photo-proof loop bound

    # --- Mock business rules -----------------------------------------------
    RETURN_WINDOW_DAYS: int = 30
    BUYERS_REMORSE_FEE: float = 5.99
    DAMAGED_FEE: float = 0.00

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Module-level singleton accessor for :class:`Settings`."""
    return Settings()


settings = get_settings()