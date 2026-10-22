from abc import ABC, abstractmethod

from detection.detector import Detection
from models.model_manager import ModelError, ModelManager


class TrackerError(Exception):
    """Message is safe to show to the user."""


class Tracker(ABC):
    @abstractmethod
    def update(self, frame) -> list[Detection]:
        """Detections for this frame; track_id is None when the tracker has no ID yet."""

    @abstractmethod
    def reset(self) -> None:
        """Forget all tracks. IDs are not stable across separate runs."""


class UltralyticsTracker(Tracker):
    def __init__(self, model: ModelManager, tracker_type: str = "bytetrack"):
        if tracker_type not in ("bytetrack", "botsort"):
            raise TrackerError(f"Unknown tracker '{tracker_type}'. Use 'bytetrack' or 'botsort'.")
        self.model, self.tracker_type = model, tracker_type

    def update(self, frame) -> list[Detection]:
        try:
            return self.model.track(frame, self.tracker_type)
        except ModelError as e:
            raise TrackerError(f"Tracking failed: {e}") from e

    def reset(self) -> None:
        self.model.reset_tracking()


if __name__ == "__main__":
    # Manual check: python -m tracking.tracker path/to/video [max_frames]
    import sys
    from itertools import islice

    from config.settings import get_settings
    from video.video_reader import read_frames

    s = get_settings()
    t = UltralyticsTracker(ModelManager(s.model_name, s.device, s.confidence_threshold, s.iou_threshold), s.tracker)
    for i, frame in islice(read_frames(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 100):
        print(i, sorted((d.class_name, d.track_id) for d in t.update(frame)))
