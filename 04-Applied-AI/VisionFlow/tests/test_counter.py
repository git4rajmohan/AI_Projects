from counting.counter import Counter
from counting.statistics import ProcessingStats
from detection.classes import DEFAULT_CLASSES
from detection.detector import Detection


def det(name, tid):
    return Detection(0, name, 0.9, 0, 0, 10, 10, tid)


def test_current_count():
    c = Counter().count_current([det("car", 1), det("car", 2), det("person", 1)])
    assert (c["car"], c["person"]) == (2, 1)


def test_unique_count_across_frames():
    c = Counter()
    c.update_unique([det("car", 1)])
    c.update_unique([det("car", 1)])
    assert c.update_unique([det("car", 1), det("car", 2)])["car"] == 2


def test_multiple_classes_separate():
    u = Counter().update_unique([det("car", 1), det("person", 2), det("bus", 3)])
    assert (u["car"], u["person"], u["bus"]) == (1, 1, 1)


def test_empty_frame_all_zero():
    c = Counter()
    assert c.count_current([]) == dict.fromkeys(DEFAULT_CLASSES, 0)
    assert c.update_unique([]) == dict.fromkeys(DEFAULT_CLASSES, 0)


def test_current_does_not_touch_unique():
    c = Counter()
    c.count_current([det("car", 1)])
    assert c.update_unique([])["car"] == 0


def test_stats_fps_and_elapsed():
    t = iter([0.0, 1.0, 2.0, 2.0, 2.0])
    s = ProcessingStats(total_frames=10, video_fps=30, clock=lambda: next(t))
    s.record(0, {}, {})  # start=0.0
    s.record(1, {"car": 1}, {"car": 1})  # 1.0
    assert s.processed_frames == 2 and len(s.history) == 2
    assert s.elapsed == 2.0  # clock -> 2.0
    assert s.processing_fps == 1.0  # 2 frames / 2.0s


def test_stats_no_zero_division():
    s = ProcessingStats(total_frames=0, video_fps=0, clock=lambda: 5.0)
    assert s.elapsed == 0.0 and s.processing_fps == 0.0
    s.record(0, {}, {})
    assert s.processing_fps == 0.0
