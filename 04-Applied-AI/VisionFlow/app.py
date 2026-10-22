import time
from pathlib import Path

import cv2
import streamlit as st

from config.settings import get_settings
from detection.classes import DEFAULT_CLASSES, supported_classes
from models.model_manager import ModelError, ModelManager
from tracking.tracker import TrackerError, UltralyticsTracker
from utils.file_utils import output_path, save_upload
from utils.logging_utils import get_logger
from video.frame_processor import process_video
from video.video_reader import SUPPORTED_EXTENSIONS, VideoValidationError, read_metadata
from video.video_writer import VideoWriteError, to_browser_mp4
from visualization.dashboard import render_analytics, render_counts, render_metadata, render_stats
from visualization.frame_viewer import render_frame_viewer

log = get_logger()
settings = get_settings()

st.set_page_config(page_title="VisionFlow", layout="wide")
log.info("VisionFlow started (model=%s, device=%s)", settings.model_name, settings.device)


@st.cache_resource
def load_manager(name: str, device: str) -> ModelManager:
    mm = ModelManager(name, device)
    mm.load_model()
    return mm


st.sidebar.title("VisionFlow")
st.sidebar.header("Input")
upload = st.sidebar.file_uploader("Upload Video", type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS])

st.sidebar.header("Detection")
models = list(dict.fromkeys([settings.model_name, "yolo11n.pt", "yolo11s.pt", "yolo11m.pt"]))
model_name = st.sidebar.selectbox("YOLO Model", models)
conf = st.sidebar.slider("Confidence Threshold", 0.0, 1.0, settings.confidence_threshold, 0.05)
iou = st.sidebar.slider("IoU Threshold", 0.0, 1.0, settings.iou_threshold, 0.05)

manager, classes = None, []
try:
    manager = load_manager(model_name, settings.device)
    manager.conf, manager.iou = conf, iou
    classes = supported_classes(manager.names)
except ModelError as e:
    st.sidebar.error(str(e))

st.sidebar.header("Object Classes")
selected = [c for c in classes if st.sidebar.checkbox(c.capitalize(), value=c in DEFAULT_CLASSES, key=f"cls_{c}")]

st.sidebar.header("Processing")
frame_skip = st.sidebar.number_input(
    "Frame Skip",
    0,
    30,
    0,
    help="Frames skipped between processed frames. Skipping can reduce tracking and counting accuracy.",
)
if frame_skip:
    st.sidebar.warning("Skipping frames can break track IDs and lower counting accuracy.")
min_area = st.sidebar.number_input(
    "Min Box Area (px²)",
    0,
    1_000_000,
    0,
    step=100,
    help="Ignore detections with a smaller box, e.g. signs or distant clutter misread as cars. 0 = off.",
)
min_track_frames = st.sidebar.number_input(
    "Min Track Length (frames)",
    1,
    300,
    5,
    help="An object counts as unique only after being tracked this many processed frames. Filters 1-2 frame flicker IDs.",
)
display_fps = st.sidebar.slider("Display FPS", 1, 30, 5, help="Max live preview refresh rate; does not affect processing.")
tracking = st.sidebar.checkbox("Tracking Enabled", value=True)
start = st.sidebar.button("Start Processing", type="primary", disabled=not (upload and manager and selected))

st.title("VisionFlow")
st.caption("AI video object detection, tracking & counting")

if not upload:
    st.info("Upload a video in the sidebar to begin.")
    st.stop()

path = save_upload(upload.name, upload.getvalue())
try:
    meta = read_metadata(path)
except VideoValidationError as e:
    log.warning("Invalid upload %s: %s", upload.name, e)
    st.error(str(e))
    st.stop()
except Exception:
    log.exception("Unexpected error reading %s", upload.name)
    st.error("Something went wrong reading the video.")
    st.stop()
log.info("Video %s: %dx%d, %.1f fps, %d frames", meta.filename, meta.width, meta.height, meta.fps, meta.frame_count)
render_metadata(meta)

if start:
    out = output_path(path, settings.output_dir)
    tracker = UltralyticsTracker(manager, settings.tracker) if tracking else None
    run = process_video(
        path,
        out,
        tracker.update if tracker else manager.detect,
        selected=selected,
        min_conf=conf,
        min_area=min_area,
        min_track_frames=min_track_frames,
        frame_skip=frame_skip,
        tracking=tracking,
        reset=tracker.reset if tracker else None,
    )
    progress, frame_ph, stats_ph, counts_ph = st.progress(0.0), st.empty(), st.empty(), st.empty()
    last_draw, last = 0.0, None
    try:
        for last in run:
            progress.progress(min((last.frame_index + 1) / max(meta.frame_count, 1), 1.0))
            now = time.perf_counter()
            if now - last_draw >= 1 / display_fps:
                last_draw = now
                frame_ph.image(cv2.cvtColor(last.annotated, cv2.COLOR_BGR2RGB), caption=f"Frame {last.frame_index}")
                with stats_ph.container():
                    render_stats(last.frame_index, last.stats)
                with counts_ph.container():
                    render_counts(last.current, last.unique, tracking)
    except (ModelError, TrackerError, VideoWriteError) as e:
        log.warning("Processing failed: %s", e)
        st.error(str(e))
        last = None
    except Exception:
        log.exception("Unexpected processing error")
        st.error("Processing failed unexpectedly. See the log for details.")
        last = None
    finally:
        run.close()
    if last:
        playable = to_browser_mp4(out)
        log.info("Output written to %s (h264=%s)", out, playable)
        st.session_state.result = dict(
            out=str(out), playable=playable, tracking=tracking, source=upload.name, frame_index=last.frame_index,
            current=last.current, unique=last.unique, stats=last.stats,
        )
        st.session_state.viewer_idx, st.session_state.viewer_playing = 0, False
        st.rerun()

res = st.session_state.get("result")
if res and res["source"] == upload.name:
    st.subheader("Results")
    render_stats(res["frame_index"], res["stats"])
    render_counts(res["current"], res["unique"], res["tracking"])
    render_analytics(res["current"], res["unique"], res["stats"], res["tracking"])
    st.subheader("Annotated video")
    if not res["playable"]:
        st.warning("ffmpeg was not found, so the video may not play in your browser. Use the download below.")
    st.video(res["out"])
    with open(res["out"], "rb") as f:
        st.download_button("Download annotated video", f, file_name=Path(res["out"]).name, mime="video/mp4")
    render_frame_viewer(res["out"], display_fps)
