import json
import time
from pathlib import Path

import cv2
import pandas as pd
import streamlit as st

from counting.counter import Counter
from detection.detector import Detection
from video.frame_processor import detections_path


def clamp(index: int, total: int) -> int:
    return max(0, min(int(index), total - 1))


def load_records(output: str | Path) -> list[dict]:
    """One record per output frame: {"frame": source index, "detections": [...]}."""
    with detections_path(output).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def read_output_frame(output: str | Path, index: int):
    cap = cv2.VideoCapture(str(output))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def _step(delta: int) -> None:
    st.session_state.viewer_idx += delta


def _toggle() -> None:
    st.session_state.viewer_playing = not st.session_state.get("viewer_playing", False)


def render_frame_viewer(output: str | Path, play_fps: int = 5) -> None:
    st.subheader("Frame viewer")
    try:
        records = load_records(output)
    except OSError:
        st.info("Frame details are not available for this run.")
        return
    if not records:
        st.info("No processed frames to view.")
        return
    last = len(records) - 1
    # Autoplay advances before the widget is built; Streamlit forbids changing its key afterwards.
    st.session_state.setdefault("viewer_idx", 0)
    if st.session_state.get("viewer_playing"):
        if st.session_state.viewer_idx < last:
            st.session_state.viewer_idx += 1
        else:
            st.session_state.viewer_playing = False
    st.session_state.viewer_idx = clamp(st.session_state.viewer_idx, len(records))
    idx = st.session_state.viewer_idx
    playing = st.session_state.get("viewer_playing", False)

    prev_c, play_c, next_c, num_c = st.columns([1, 1, 1, 2])
    prev_c.button("Previous Frame", on_click=_step, args=(-1,), disabled=idx == 0)
    play_c.button("Stop" if playing else "Play", on_click=_toggle)
    next_c.button("Next Frame", on_click=_step, args=(1,), disabled=idx == last)
    num_c.number_input("Output frame", 0, last, key="viewer_idx")

    rec = records[idx]
    frame = read_output_frame(output, idx)
    if frame is None:
        st.warning("Could not read this frame from the output video.")
    else:
        st.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), caption=f"Output frame {idx} (source frame {rec['frame']})")
    dets = [Detection(**d) for d in rec["detections"]]
    st.markdown("**Current counts (this frame)**")
    st.dataframe(pd.DataFrame([Counter().count_current(dets)]), width='stretch', hide_index=True)
    st.markdown("**Detections**")
    if dets:
        st.dataframe(
            pd.DataFrame(
                [(d.class_name, d.track_id, round(d.confidence, 2), d.x1, d.y1, d.x2, d.y2) for d in dets],
                columns=["Class", "ID", "Confidence", "x1", "y1", "x2", "y2"],
            ),
            width='stretch',
            hide_index=True,
        )
    else:
        st.caption("No detections in this frame.")
    if playing:
        time.sleep(1 / play_fps)
        st.rerun()
