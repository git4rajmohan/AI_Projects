from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import cv2

SUPPORTED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


class VideoValidationError(Exception):
    """Message is safe to show to the user."""


@dataclass(frozen=True)
class VideoMetadata:
    filename: str
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


@contextmanager
def _open(path: str | Path):
    cap = cv2.VideoCapture(str(path))
    try:
        yield cap
    finally:
        cap.release()


def read_metadata(path: str | Path) -> VideoMetadata:
    """Validate the video and return its metadata."""
    p = Path(path)
    if not p.is_file():
        raise VideoValidationError("Video file not found.")
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise VideoValidationError(f"Unsupported format. Use: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.")
    with _open(p) as cap:
        if not cap.isOpened():
            raise VideoValidationError("Could not open the video; it may be corrupt.")
        ok, _ = cap.read()
        if not ok:
            raise VideoValidationError("Could not read any frames from the video.")
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps, count = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not (w and h and fps > 0):
        raise VideoValidationError("Video is missing resolution or FPS information.")
    return VideoMetadata(p.name, w, h, fps, count)


def read_frames(path: str | Path, frame_skip: int = 0) -> Iterator[tuple[int, "cv2.typing.MatLike"]]:
    """Yield (frame_index, frame) one at a time, skipping `frame_skip` frames between yields."""
    step = frame_skip + 1
    with _open(path) as cap:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            if i % step == 0:
                yield i, frame
            i += 1
