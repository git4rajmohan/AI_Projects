from collections import Counter
from collections.abc import Iterable

from detection.classes import DEFAULT_CLASSES
from detection.detector import Detection


class TrackState:
    """Distinct track IDs observed during one run, each counted once under its majority class.

    An ID only counts after `min_frames` sightings, which drops 1-2 frame flicker tracks.
    """

    def __init__(self, classes: Iterable[str] = DEFAULT_CLASSES, min_frames: int = 1):
        self._classes = tuple(classes)
        self.min_frames = min_frames
        self._votes: dict[int, Counter] = {}

    def update(self, detections: Iterable[Detection]) -> None:
        for d in detections:
            if d.track_id is not None:
                self._votes.setdefault(d.track_id, Counter())[d.class_name] += 1

    def unique_counts(self) -> dict[str, int]:
        counts = dict.fromkeys(self._classes, 0)
        for votes in self._votes.values():
            if votes.total() >= self.min_frames:
                cls = votes.most_common(1)[0][0]
                counts[cls] = counts.get(cls, 0) + 1
        return counts

    def reset(self) -> None:
        self._votes = {}
