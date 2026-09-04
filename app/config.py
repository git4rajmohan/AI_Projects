"""
Application configuration — loads from .env via pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Ollama Cloud (via proxy) ──────────────────────────────────────────────
    ollama_api_key: str = ""
    openai_api_key: str = "ollama-cloud-proxy"
    openai_api_base: str = "http://127.0.0.1:11435/v1"
    ollama_model: str = "openai/gpt-oss:120b"

    # ── Twilio (SMS) ──────────────────────────────────────────────────────────
    twilio_account_sid: str = "mock"
    twilio_auth_token: str = "mock"
    twilio_from_number: str = "+10000000000"

    # ── App ───────────────────────────────────────────────────────────────────
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    @property
    def is_twilio_mock(self) -> bool:
        """True when Twilio creds are not configured (mock mode)."""
        return self.twilio_account_sid in ("mock", "", "your_twilio_sid")


# Singleton
settings = Settings()