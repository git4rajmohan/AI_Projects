import cv2
import numpy as np
import pytest

from utils.file_utils import output_path, save_upload
from video.video_reader import VideoValidationError, read_frames, read_metadata


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for i in range(10):
        w.write(np.full((48, 64, 3), i * 20, dtype=np.uint8))
    w.release()
    return path


def test_metadata(video):
    m = read_metadata(video)
    assert (m.filename, m.width, m.height, m.frame_count) == ("clip.avi", 64, 48, 10)
    assert m.fps == 10 and m.duration == pytest.approx(1.0)


def test_missing_file(tmp_path):
    with pytest.raises(VideoValidationError):
        read_metadata(tmp_path / "nope.mp4")


def test_unsupported_extension(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    with pytest.raises(VideoValidationError, match="Unsupported"):
        read_metadata(p)


def test_corrupt_and_empty(tmp_path):
    for data in (b"", b"not a video"):
        p = tmp_path / "bad.mp4"
        p.write_bytes(data)
        with pytest.raises(VideoValidationError):
            read_metadata(p)


def test_reader_frames_and_skip(video):
    assert [i for i, _ in read_frames(video)] == list(range(10))
    assert [i for i, _ in read_frames(video, frame_skip=2)] == [0, 3, 6, 9]


def test_reader_releases_on_early_exit(video, monkeypatch):
    released = []
    real = cv2.VideoCapture

    class Spy:
        def __init__(self, *a):
            self.cap = real(*a)

        def release(self):
            released.append(True)
            self.cap.release()

        def __getattr__(self, n):
            return getattr(self.cap, n)

    monkeypatch.setattr(cv2, "VideoCapture", Spy)
    gen = read_frames(video)
    next(gen)
    gen.close()
    assert released


def test_save_upload_sanitizes(tmp_path):
    p = save_upload("../../evil name?.mp4", b"x", tmp_path)
    assert p.parent == tmp_path and p.read_bytes() == b"x"
    assert ".." not in p.name and "?" not in p.name


def test_output_path():
    assert output_path("data/input/traffic.mov", "out").as_posix() == "out/traffic_annotated.mp4"


# --- processing pipeline ---
import json

from detection.detector import Detection
from video import frame_processor
from video.frame_processor import detections_path, process_video
from video.video_writer import VideoWriteError, open_writer


def fake_detect(frame):
    return [Detection(2, "car", 0.9, 5, 5, 30, 30, 1), Detection(0, "person", 0.2, 0, 0, 9, 9, 2)]


def run(video, dst, **kw):
    return list(process_video(video, dst, fake_detect, selected=["car", "person"], min_conf=0.5, **kw))


def test_end_to_end_output_and_counts(video, tmp_path):
    dst = tmp_path / "out" / "clip_annotated.mp4"
    res = run(video, dst)
    assert len(res) == 10 and res[-1].current["car"] == 1 and res[-1].unique["car"] == 1
    assert res[-1].current["person"] == 0  # filtered by confidence
    cap = cv2.VideoCapture(str(dst))
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    assert n == 10
    lines = detections_path(dst).read_text().splitlines()
    assert len(lines) == 10 and json.loads(lines[0])["detections"][0]["track_id"] == 1


def test_frame_skip_and_tracking_off(video, tmp_path):
    res = run(video, tmp_path / "o.mp4", frame_skip=2, tracking=False)
    assert [r.frame_index for r in res] == [0, 3, 6, 9]
    assert all(r.unique == {} for r in res)


def test_tracker_reset_called_even_when_closed_early(video, tmp_path):
    calls = []
    gen = process_video(video, tmp_path / "o.mp4", fake_detect, selected=["car"], reset=lambda: calls.append(1))
    next(gen)
    gen.close()
    assert len(calls) == 2


def test_writer_released_when_processing_raises(video, tmp_path, monkeypatch):
    released = []
    real = cv2.VideoWriter

    class Spy:
        def __init__(self, *a):
            self.w = real(*a)

        def release(self):
            released.append(True)
            self.w.release()

        def __getattr__(self, n):
            return getattr(self.w, n)

    def boom(frame):
        raise RuntimeError("boom")

    monkeypatch.setattr(cv2, "VideoWriter", Spy)
    monkeypatch.setattr(cv2, "VideoWriter_fourcc", real.fourcc)
    with pytest.raises(RuntimeError):
        list(process_video(video, tmp_path / "o.mp4", boom, selected=["car"]))
    assert released

def test_writer_open_failure(tmp_path):
    with pytest.raises(VideoWriteError):
        with open_writer(tmp_path / "x.mp4", 10, (0, 0)):
            pass


def test_output_name_from_original():
    assert output_path("a/My Clip.mov", "o").name == "My Clip_annotated.mp4"
