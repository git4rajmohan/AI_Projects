from config.settings import get_settings


def test_settings_load():
    s = get_settings()
    assert 0 <= s.confidence_threshold <= 1
    assert 0 <= s.iou_threshold <= 1
    assert s.device in {"auto", "cpu", "cuda"} or s.device.startswith("cuda")
    assert "ollama_api_key" not in repr(s)
