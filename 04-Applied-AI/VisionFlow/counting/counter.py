from collections.abc import Iterable

from detection.classes import DEFAULT_CLASSES
from detection.detector import Detection
from tracking.track_state import TrackState


class Counter:
    """Current (this frame) and unique (distinct track IDs) counts; kept separate.

    ponytail: line-crossing count is post-MVP, add as its own method/state.
    """

    def __init__(self, classes: Iterable[str] = DEFAULT_CLASSES, min_track_frames: int = 1):
        self._classes = tuple(classes)
        self._state = TrackState(self._classes, min_track_frames)

    def count_current(self, detections: Iterable[Detection]) -> dict[str, int]:
        counts = dict.fromkeys(self._classes, 0)
        for d in detections:
            counts[d.class_name] = counts.get(d.class_name, 0) + 1
        return counts

    def update_unique(self, detections: Iterable[Detection]) -> dict[str, int]:
        self._state.update(detections)
        return self._state.unique_counts()

    def reset(self) -> None:
        self._state.reset()
