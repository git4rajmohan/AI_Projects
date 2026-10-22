# Central configuration — the ONLY place that reads .env (spec section 4).
# Never hard-code model names elsewhere; import from here.

import os

from dotenv import load_dotenv

load_dotenv()

# Local Ollama — serves the Tev1 decision model (/v1/systemone)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
TEV1_MODEL = os.getenv("TEV1_MODEL", "tev1:4b")

# Ollama Cloud — generative LLM (deviation note in plan.md: separate host from OLLAMA_HOST)
OLLAMA_CLOUD_HOST = os.getenv("OLLAMA_CLOUD_HOST", "https://ollama.com")
OLLAMA_CLOUD_MODEL = os.getenv("OLLAMA_CLOUD_MODEL")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

# ---------------------------------------------------------------- MaintAI ---
# Generative LLM for maintenance explanations (spec1 §5.2): local or cloud,
# defaulting to the playground cloud config above so one key serves both.
# ponytail: empty .env value means reuse the cloud model — no separate config path
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL") or OLLAMA_CLOUD_MODEL
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or OLLAMA_CLOUD_HOST

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///maintai.db")

TEV1_TIMEOUT_SECONDS = int(os.getenv("TEV1_TIMEOUT_SECONDS", "120"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
TEV1_CONFIDENCE_REVIEW_THRESHOLD = float(
    os.getenv("TEV1_CONFIDENCE_REVIEW_THRESHOLD", "0.70")
)
ENABLE_SYNTHETIC_DATA = os.getenv("ENABLE_SYNTHETIC_DATA", "true").lower() != "false"

# Demonstration tuning defaults (spec1 §6.1) — not universal limits.
SENSOR_FRESHNESS_MINUTES = int(os.getenv("SENSOR_FRESHNESS_MINUTES", "180"))
TREND_WINDOW_READINGS = int(os.getenv("TREND_WINDOW_READINGS", "12"))
MAX_MISSING_READINGS = int(os.getenv("MAX_MISSING_READINGS", "3"))
TEMPERATURE_ROC_C_PER_H = float(os.getenv("TEMPERATURE_ROC_C_PER_H", "10"))
VIBRATION_ROC_MM_S_PER_H = float(os.getenv("VIBRATION_ROC_MM_S_PER_H", "2"))
MOTOR_LOAD_ROC_PCT_PER_H = float(os.getenv("MOTOR_LOAD_ROC_PCT_PER_H", "15"))


def validate_settings():
    """Return user-friendly messages for missing required settings.

    Never includes key VALUES — only names, per spec sections 19 and 25.
    """
    messages = []
    if not OLLAMA_CLOUD_MODEL:
        messages.append("OLLAMA_CLOUD_MODEL is not configured in .env.")
    if not OLLAMA_API_KEY:
        messages.append("OLLAMA_API_KEY is not configured in .env.")
    return messages


def is_configured():
    """Preflight flags for the Streamlit sidebar."""
    return {
        "cloud_llm": bool(OLLAMA_CLOUD_MODEL and OLLAMA_API_KEY),
        "local_ollama": bool(OLLAMA_HOST),
    }


def maintai_is_configured():
    """MaintAI preflight flags (spec1 §5.2)."""
    return {
        "tev1": bool(OLLAMA_HOST and TEV1_MODEL),
        "llm": bool(LLM_MODEL and LLM_BASE_URL),
        "synthetic_data": ENABLE_SYNTHETIC_DATA,
    }