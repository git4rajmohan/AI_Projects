from types import SimpleNamespace

import numpy as np
import pytest
import torch

from detection.classes import DEFAULT_CLASSES, supported_classes
from detection.detector import Detection, filter_detections
from models.model_manager import ModelError, resolve_device, results_to_detections


def det(name="car", conf=0.6):
    return Detection(0, name, conf, 0, 0, 10, 10)


def test_confidence_boundary_included():
    kept = filter_detections([det(conf=0.5), det(conf=0.49)], 0.5, ["car"])
    assert [d.confidence for d in kept] == [0.5]


def test_class_filtering():
    ds = [det("car"), det("person"), det("dog")]
    assert [d.class_name for d in filter_detections(ds, 0.0, ["car", "person"])] == ["car", "person"]
    assert filter_detections(ds, 0.0, []) == []
    assert filter_detections(ds, 0.0, ["unicorn"]) == []


def test_min_area_filter():
    small, big = Detection(0, "car", 0.9, 0, 0, 10, 10), Detection(0, "car", 0.9, 0, 0, 50, 40)
    assert filter_detections([small, big], 0.0, ["car"], min_area=101) == [big]
    assert filter_detections([small, big], 0.0, ["car"], min_area=100) == [small, big]


def test_supported_classes_intersection():
    assert supported_classes({0: "person", 1: "car", 2: "dog"}) == ["person", "car"]
    assert supported_classes({}) == []
    assert supported_classes(dict(enumerate(DEFAULT_CLASSES))) == list(DEFAULT_CLASSES)


def fake_result(ids):
    boxes = SimpleNamespace(
        xyxy=np.array([[1.2, 2.7, 30.0, 40.0], [5, 5, 9, 9]]),
        conf=np.array([0.91, 0.4]),
        cls=np.array([2.0, 0.0]),
        id=ids,
    )
    return SimpleNamespace(boxes=boxes, names={0: "person", 2: "car"})


def test_results_conversion_with_ids():
    car, person = results_to_detections(fake_result(np.array([17.0, 3.0])))
    assert (car.class_name, car.track_id, car.x1, car.y1, car.x2, car.y2) == ("car", 17, 1, 2, 30, 40)
    assert car.confidence == pytest.approx(0.91)
    assert (person.class_name, person.track_id) == ("person", 3)


def test_results_conversion_without_ids_or_boxes():
    assert [d.track_id for d in results_to_detections(fake_result(None))] == [None, None]
    empty = SimpleNamespace(boxes=SimpleNamespace(xyxy=np.zeros((0, 4)), conf=np.array([]), cls=np.array([]), id=None), names={})
    assert results_to_detections(empty) == []
    assert results_to_detections(SimpleNamespace(boxes=None, names={})) == []


def test_resolve_device(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("auto") == "cpu"
    assert resolve_device("cpu") == "cpu"
    with pytest.raises(ModelError):
        resolve_device("cuda")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_device("auto") == "cuda"
