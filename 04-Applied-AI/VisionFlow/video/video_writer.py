import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import cv2


class VideoWriteError(Exception):
    """Message is safe to show to the user."""


@contextmanager
def open_writer(path: str | Path, fps: float, size: tuple[int, int]) -> Iterator[cv2.VideoWriter]:
    """mp4v writer that always releases. Overwrites an existing file. size is (width, height)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    try:
        if not writer.isOpened():
            raise VideoWriteError("Could not create the output video file.")
        yield writer
    finally:
        writer.release()


def to_browser_mp4(path: str | Path) -> bool:
    """Re-encode mp4v -> H.264 in place so browsers can play it. Returns False if ffmpeg is missing or fails."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    p = Path(path)
    tmp = p.with_name(f"{p.stem}_h264.mp4")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(p), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp)]
    if subprocess.run(cmd, check=False).returncode != 0:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(p)
    return True
