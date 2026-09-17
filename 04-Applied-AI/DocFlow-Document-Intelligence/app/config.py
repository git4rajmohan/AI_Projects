from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Ollama cloud (OpenAI-compatible)
    ollama_api_key: str = "PASTE_YOUR_KEY_HERE"
    ollama_base_url: str = "https://ollama.com/v1"
    ollama_model: str = "gpt-oss:120b"

    db_path: str = "data/docflow.db"
    extraction_mode: str = "mock"  # mock | live

    # OCR fallback for image-only / scanned pages (§19 document processing)
    ocr_mode: str = "auto"  # auto | off | only
    tessdata_dir: str = ""  # optional TESSDATA_PREFIX for Windows installs

    # Deterministic policy thresholds — the LLM never sees these
    auto_approve_limit: int = 100_000
    manager_limit: int = 1_000_000
    price_tolerance_pct: float = 0.5
    qty_tolerance: int = 0
    confidence_floor: float = 0.6
    max_invoice_age_days: int = 180  # date-sanity: invoice can't be older than this


settings = Settings()