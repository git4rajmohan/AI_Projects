import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "yolo11n.pt"))
    confidence_threshold: float = field(default_factory=lambda: float(os.getenv("CONFIDENCE_THRESHOLD", "0.50")))
    iou_threshold: float = field(default_factory=lambda: float(os.getenv("IOU_THRESHOLD", "0.50")))
    device: str = field(default_factory=lambda: os.getenv("DEVICE", "auto"))
    tracker: str = field(default_factory=lambda: os.getenv("TRACKER", "bytetrack"))  # bytetrack | botsort
    output_dir: str = field(default_factory=lambda: os.getenv("OUTPUT_DIR", "data/output"))
    # Kept out of repr so the key never lands in logs.
    ollama_api_key: str = field(default_factory=lambda: os.getenv("OLLAMA_API_KEY", ""), repr=False)
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "https://ollama.com"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "glm-5.3-flash"))


def get_settings() -> Settings:
    return Settings()
