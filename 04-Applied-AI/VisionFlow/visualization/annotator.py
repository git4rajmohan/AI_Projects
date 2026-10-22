import cv2

from detection.detector import Detection

FONT = cv2.FONT_HERSHEY_SIMPLEX
_PALETTE = ((0, 200, 0), (255, 128, 0), (0, 0, 255), (200, 0, 200), (0, 200, 200), (255, 0, 0))


def color_for(class_id: int) -> tuple[int, int, int]:
    return _PALETTE[class_id % len(_PALETTE)]


def label_text(d: Detection) -> str:
    tid = f" #{d.track_id}" if d.track_id is not None else ""
    return f"{d.class_name.upper()}{tid} {d.confidence:.2f}"


def annotate(frame, detections, frame_index: int, counts: dict[str, int] | None = None):
    """Draw boxes, labels, frame number and optional counts on a copy of the frame."""
    out = frame.copy()
    h, w = out.shape[:2]
    for d in detections:
        color = color_for(d.class_id)
        text = label_text(d)
        cv2.rectangle(out, (d.x1, d.y1), (d.x2, d.y2), color, 2)
        (tw, th), base = cv2.getTextSize(text, FONT, 0.5, 1)
        x = min(max(d.x1, 0), max(w - tw, 0))
        y = min(max(d.y1, th + base), h - base)  # keeps the label inside the frame
        cv2.rectangle(out, (x, y - th - base), (x + tw, y + base), color, -1)
        cv2.putText(out, text, (x, y), FONT, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    lines = [f"Frame: {frame_index}"]
    if counts:
        lines += [f"{c}: {n}" for c, n in counts.items() if n]
    for i, text in enumerate(lines):
        pos = (10, 22 + 20 * i)
        cv2.putText(out, text, pos, FONT, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, text, pos, FONT, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return out
