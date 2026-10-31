"""A2A_* settings loaded once from .env / environment."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() == "true"


@dataclass(frozen=True)
class Settings:
    default_timeout: float = float(os.getenv("A2A_DEFAULT_TIMEOUT_SECONDS", "30"))
    task_timeout: float = float(os.getenv("A2A_TASK_TIMEOUT_SECONDS", "180"))
    poll_interval: float = float(os.getenv("A2A_POLL_INTERVAL_SECONDS", "2"))
    max_card_bytes: int = int(os.getenv("A2A_MAX_CARD_BYTES", "1048576"))
    max_redirects: int = int(os.getenv("A2A_MAX_REDIRECTS", "0"))
    require_https: bool = _bool("A2A_REQUIRE_HTTPS", "true")
    allow_local_agents: bool = _bool("ALLOW_LOCAL_AGENTS", "false")
    # optional comma-separated allowlist; empty = any public host
    allowed_domains: frozenset[str] = field(
        default_factory=lambda: frozenset(
            h.strip().lower()
            for h in os.getenv("A2A_ALLOWED_DOMAINS", "").split(",")
            if h.strip()
        )
    )


settings = Settings()
