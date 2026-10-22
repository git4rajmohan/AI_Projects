import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FrameRecord:
    frame_index: int
    current: dict[str, int]
    unique: dict[str, int]


@dataclass
class ProcessingStats:
    total_frames: int
    video_fps: float
    clock: Callable[[], float] = time.perf_counter
    processed_frames: int = 0
    history: list[FrameRecord] = field(default_factory=list)
    _start: float | None = field(default=None, repr=False)

    def record(self, frame_index: int, current: dict[str, int], unique: dict[str, int]) -> None:
        now = self.clock()
        if self._start is None:
            self._start = now
        self.processed_frames += 1
        self.history.append(FrameRecord(frame_index, dict(current), dict(unique)))

    @property
    def elapsed(self) -> float:
        return 0.0 if self._start is None else self.clock() - self._start

    @property
    def processing_fps(self) -> float:
        e = self.elapsed
        return self.processed_frames / e if e > 0 else 0.0
