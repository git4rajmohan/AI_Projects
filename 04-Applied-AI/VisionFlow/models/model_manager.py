import sys

import torch

from config.settings import get_settings
from detection.detector import Detection
from utils.logging_utils import get_logger

log = get_logger()


class ModelError(Exception):
    """Message is safe to show to the user."""


def resolve_device(requested: str) -> str:
    cuda = torch.cuda.is_available()
    if requested == "auto":
        return "cuda" if cuda else "cpu"
    if requested.startswith("cuda") and not cuda:
        raise ModelError("CUDA was requested but is not available. Set DEVICE=cpu or DEVICE=auto.")
    return requested


def results_to_detections(result) -> list[Detection]:
    """Convert one Ultralytics result into Detections (track_id is None when untracked)."""
    boxes = result.boxes
    if boxes is None or len(boxes.conf) == 0:
        return []
    ids = boxes.id.tolist() if boxes.id is not None else [None] * len(boxes.conf)
    return [
        Detection(int(c), result.names[int(c)], float(p), *(int(v) for v in xyxy), None if i is None else int(i))
        for xyxy, p, c, i in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist(), ids)
    ]


class ModelManager:
    def __init__(self, model_name: str, device: str = "auto", conf: float = 0.5, iou: float = 0.5):
        self.model_name, self.conf, self.iou = model_name, conf, iou
        self.device = resolve_device(device)
        self._model = None

    def load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO

            self._model = YOLO(self.model_name)
        except Exception as e:
            log.exception("Failed to load model %s", self.model_name)
            raise ModelError(f"Could not load model '{self.model_name}'. Check the name and your connection.") from e
        log.info("Loaded model %s on %s", self.model_name, self.device)

    @property
    def names(self) -> dict[int, str]:
        self.load_model()
        return self._model.names

    def _run(self, fn, frame, **kw) -> list[Detection]:
        self.load_model()
        try:
            res = fn(frame, conf=self.conf, iou=self.iou, device=self.device, verbose=False, **kw)
        except torch.cuda.OutOfMemoryError as e:
            raise ModelError("GPU ran out of memory. Try a smaller model, CPU, or a higher frame skip.") from e
        except Exception as e:
            log.exception("Inference failed")
            raise ModelError("Detection failed on this frame.") from e
        return results_to_detections(res[0])

    def detect(self, frame) -> list[Detection]:
        self.load_model()
        return self._run(self._model.predict, frame)

    def track(self, frame, tracker: str = "bytetrack") -> list[Detection]:
        self.load_model()
        return self._run(self._model.track, frame, persist=True, tracker=f"{tracker}.yaml")

    def reset_tracking(self) -> None:
        # Dropping the predictor makes Ultralytics build fresh trackers on the next track() call.
        if self._model is not None:
            self._model.predictor = None


if __name__ == "__main__":
    # Smoke check: python -m models.model_manager path/to/video
    from video.video_reader import read_frames

    s = get_settings()
    mm = ModelManager(s.model_name, s.device, s.confidence_threshold, s.iou_threshold)
    _, frame = next(read_frames(sys.argv[1]))
    for d in mm.detect(frame):
        print(d)
