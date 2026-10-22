import json

import cv2
import numpy as np

from visualization.frame_viewer import clamp, load_records, read_output_frame


def test_clamp_bounds():
    assert [clamp(i, 5) for i in (-3, 0, 4, 5, 99)] == [0, 0, 4, 4, 4]


def test_skipped_frame_mapping_and_seek(tmp_path):
    out = tmp_path / "clip_annotated.mp4"
    w = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
    for v in (10, 100, 200):
        w.write(np.full((24, 32, 3), v, dtype=np.uint8))
    w.release()
    # Output frames 0..2 come from source frames 0, 3, 6 (frame_skip=2).
    lines = [json.dumps({"frame": f, "detections": []}) for f in (0, 3, 6)]
    (tmp_path / "clip_annotated.mp4.jsonl").write_text("\n".join(lines))

    records = load_records(out)
    assert [r["frame"] for r in records] == [0, 3, 6]
    assert read_output_frame(out, 2).mean() > read_output_frame(out, 0).mean()
    assert read_output_frame(out, 50) is None
