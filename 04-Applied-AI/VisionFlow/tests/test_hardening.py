import pytest
import torch

from models.model_manager import ModelError, ModelManager
from tracking.tracker import TrackerError, UltralyticsTracker


class FailingModel:
    def __init__(self, exc):
        self.exc = exc

    def predict(self, *a, **k):
        raise self.exc

    track = predict


def manager(exc) -> ModelManager:
    mm = ModelManager("fake.pt", "cpu")
    mm._model = FailingModel(exc)  # skips load_model, so no weights or download needed
    return mm


def test_forced_cpu_needs_no_cuda(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert ModelManager("fake.pt", "cpu").device == "cpu"


def test_oom_gives_friendly_message():
    with pytest.raises(ModelError, match="out of memory"):
        manager(torch.cuda.OutOfMemoryError("boom")).detect(None)


def test_inference_failure_hides_internals():
    with pytest.raises(ModelError) as e:
        manager(RuntimeError("secret/path/trace")).detect(None)
    assert "secret" not in str(e.value)


def test_tracker_failure_is_typed():
    with pytest.raises(TrackerError):
        UltralyticsTracker(manager(RuntimeError("x"))).update(None)


def test_unknown_tracker_rejected():
    with pytest.raises(TrackerError):
        UltralyticsTracker(manager(RuntimeError("x")), "nope")
