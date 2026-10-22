import pandas as pd
import streamlit as st

from counting.statistics import ProcessingStats
from video.video_reader import VideoMetadata


def render_metadata(meta: VideoMetadata) -> None:
    st.subheader("Video info")
    c = st.columns(5)
    c[0].metric("File", meta.filename)
    c[1].metric("Resolution", f"{meta.width}x{meta.height}")
    c[2].metric("FPS", f"{meta.fps:.2f}")
    c[3].metric("Frames", meta.frame_count)
    c[4].metric("Duration", f"{meta.duration:.1f}s")


def counts_frame(current: dict[str, int], unique: dict[str, int]) -> pd.DataFrame:
    classes = list(dict.fromkeys([*current, *unique]))
    return pd.DataFrame(
        {"Current": [current.get(c, 0) for c in classes], "Unique": [unique.get(c, 0) for c in classes]},
        index=pd.Index([c.capitalize() for c in classes], name="Class"),
    )


def render_counts(current: dict[str, int], unique: dict[str, int], tracking: bool) -> None:
    df = counts_frame(current, unique)
    left, right = st.columns(2)
    left.markdown("**Current Objects**")
    left.dataframe(df[["Current"]], width='stretch')
    right.markdown("**Unique Tracked Objects**")
    if tracking:
        right.dataframe(df[["Unique"]], width='stretch')
    else:
        right.info("Tracking is off, so unique objects are not counted.")


def render_stats(frame_index: int, stats: ProcessingStats) -> None:
    c = st.columns(6)
    c[0].metric("Frame", frame_index)
    c[1].metric("Video FPS", f"{stats.video_fps:.2f}")
    c[2].metric("Processing FPS", f"{stats.processing_fps:.2f}")
    c[3].metric("Processed", stats.processed_frames)
    c[4].metric("Total frames", stats.total_frames)
    c[5].metric("Elapsed", f"{stats.elapsed:.1f}s")


def render_analytics(current: dict[str, int], unique: dict[str, int], stats: ProcessingStats, tracking: bool) -> None:
    st.subheader("Analytics")
    df = counts_frame(current, unique)
    if not tracking:
        df = df[["Current"]]
    st.dataframe(df, width='stretch')
    if df.to_numpy().sum() > 0:
        st.bar_chart(df)
    if len(stats.history) >= 2:
        series = pd.DataFrame([r.current for r in stats.history], index=[r.frame_index for r in stats.history])
        st.markdown("**Current objects over time**")
        st.line_chart(series)
