from app.config import settings


def test_settings_load():
    assert settings.auto_approve_limit == 100_000
    assert settings.manager_limit == 1_000_000
    assert 0 < settings.confidence_floor < 1
    assert settings.extraction_mode in ("mock", "live")
    assert settings.ollama_base_url.startswith("http")