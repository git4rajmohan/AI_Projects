from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    track_id: int | None = None


def filter_detections(
    detections: Iterable[Detection], min_confidence: float, selected_classes: Iterable[str], min_area: int = 0
) -> list[Detection]:
    """Keep detections with confidence >= min_confidence, a selected class and box area >= min_area px²."""
    selected = set(selected_classes)
    return [
        d
        for d in detections
        if d.confidence >= min_confidence and d.class_name in selected and (d.x2 - d.x1) * (d.y2 - d.y1) >= min_area
    ]
