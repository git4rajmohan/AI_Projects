import numpy as np

from detection.detector import Detection
from visualization.annotator import annotate, label_text


def det(name="car", tid=17, conf=0.91, box=(20, 20, 60, 60)):
    return Detection(2, name, conf, *box, tid)


def blank():
    return np.zeros((100, 120, 3), dtype=np.uint8)


def test_label_text():
    assert label_text(det("car", 17, 0.91)) == "CAR #17 0.91"
    assert label_text(det("bus", 3, 0.87)) == "BUS #3 0.87"
    assert label_text(det("person", None, 0.94)) == "PERSON 0.94"


def test_shape_dtype_and_input_untouched():
    f = blank()
    out = annotate(f, [det()], 5)
    assert out.shape == f.shape and out.dtype == f.dtype
    assert out.any() and not f.any()


def test_no_detections_only_frame_overlay_changes_pixels():
    out = annotate(blank(), [], 0)
    assert out[50:].sum() == 0  # overlay stays in the top-left; box area untouched


def test_counts_overlay_changes_output():
    f = blank()
    assert not np.array_equal(annotate(f, [], 0), annotate(f, [], 0, {"car": 3}))


def test_edge_detections_do_not_raise():
    for box in [(0, 0, 10, 10), (110, 90, 119, 99), (-5, -5, 5, 5), (100, 0, 400, 400)]:
        annotate(blank(), [det(box=box)], 1)
