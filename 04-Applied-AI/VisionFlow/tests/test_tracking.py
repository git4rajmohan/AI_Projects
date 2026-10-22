from types import SimpleNamespace

import pytest

from detection.detector import Detection
from models.model_manager import ModelError
from tracking.track_state import TrackState
from tracking.tracker import Tracker, TrackerError, UltralyticsTracker


def det(name="car", tid=None):
    return Detection(0, name, 0.9, 0, 0, 10, 10, tid)


def test_new_id_added_and_duplicate_ignored():
    s = TrackState()
    s.update([det("car", 1)])
    s.update([det("car", 1)])
    assert s.unique_counts()["car"] == 1
    s.update([det("car", 2)])
    assert s.unique_counts()["car"] == 2


def test_different_ids_in_different_classes_are_separate():
    s = TrackState()
    s.update([det("car", 1), det("person", 2)])
    assert (s.unique_counts()["car"], s.unique_counts()["person"]) == (1, 1)


def test_min_frames_drops_flicker_ids():
    s = TrackState(min_frames=3)
    for _ in range(2):
        s.update([det("truck", 1)])
    assert s.unique_counts()["truck"] == 0
    s.update([det("truck", 1)])
    assert s.unique_counts()["truck"] == 1


def test_id_counts_once_under_majority_class():
    s = TrackState()
    for name in ["bus"] * 5 + ["truck"] * 2:
        s.update([det(name, 7)])
    assert (s.unique_counts()["bus"], s.unique_counts()["truck"]) == (1, 0)


def test_none_ids_ignored_and_reset_clears():
    s = TrackState()
    s.update([det("car", None), det("bus", 5)])
    assert s.unique_counts()["car"] == 0 and s.unique_counts()["bus"] == 1
    s.reset()
    assert sum(s.unique_counts().values()) == 0


def test_unknown_class_is_tracked():
    s = TrackState()
    s.update([det("dog", 1)])
    assert s.unique_counts()["dog"] == 1


class FakeTracker(Tracker):
    def __init__(self):
        self.n = 0

    def update(self, frame):
        self.n += 1
        return [det("car", 1)]

    def reset(self):
        self.n = 0


def test_fake_tracker_is_swappable():
    t, s = FakeTracker(), TrackState()
    for _ in range(3):
        s.update(t.update(None))
    assert s.unique_counts()["car"] == 1
    t.reset()
    assert t.n == 0


def test_ultralytics_tracker_wraps_errors_and_delegates():
    calls = []

    class Model:
        def track(self, frame, tracker):
            calls.append(tracker)
            raise ModelError("boom")

        def reset_tracking(self):
            calls.append("reset")

    t = UltralyticsTracker(Model(), "botsort")
    with pytest.raises(TrackerError, match="boom"):
        t.update(None)
    t.reset()
    assert calls == ["botsort", "reset"]


def test_unknown_tracker_type_rejected():
    with pytest.raises(TrackerError):
        UltralyticsTracker(SimpleNamespace(), "nope")
