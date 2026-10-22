import json
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from counting.counter import Counter
from counting.statistics import ProcessingStats
from detection.detector import Detection, filter_detections
from utils.logging_utils import get_logger
from video.video_reader import read_frames, read_metadata
from video.video_writer import open_writer
from visualization.annotator import annotate

log = get_logger(__name__)


@dataclass
class FrameResult:
    frame_index: int  # index in the source video
    annotated: object  # latest annotated frame (numpy array); not retained after the next yield
    detections: list[Detection]
    current: dict[str, int]
    unique: dict[str, int]  # empty when tracking is off
    stats: ProcessingStats


def detections_path(output: str | Path) -> Path:
    return Path(f"{output}.jsonl")


def process_video(
    src: str | Path,
    dst: str | Path,
    detect: Callable[[object], list[Detection]],
    *,
    selected: list[str],
    min_conf: float = 0.0,
    min_area: int = 0,
    min_track_frames: int = 1,
    frame_skip: int = 0,
    tracking: bool = True,
    reset: Callable[[], None] | None = None,
) -> Iterator[FrameResult]:
    """Stream read -> detect -> filter -> count -> annotate -> write, yielding one result per frame.

    Skipped frames are neither processed nor written; the output plays at fps/(frame_skip+1) to keep
    its real duration. Line N of `<dst>.jsonl` holds the detections of output frame N and its source index.
    Closing the generator early still releases the reader, writer and tracker state.
    """
    meta = read_metadata(src)
    counter, stats = Counter(min_track_frames=min_track_frames), ProcessingStats(meta.frame_count, meta.fps)
    unique: dict[str, int] = {}
    log.info("Processing %s -> %s (skip=%d, tracking=%s)", meta.filename, dst, frame_skip, tracking)
    if reset:
        reset()
    try:
        with (
            open_writer(dst, meta.fps / (frame_skip + 1), (meta.width, meta.height)) as writer,
            detections_path(dst).open("w", encoding="utf-8") as sidecar,
        ):
            for i, frame in read_frames(src, frame_skip):
                dets = filter_detections(detect(frame), min_conf, selected, min_area)
                current = counter.count_current(dets)
                unique = counter.update_unique(dets) if tracking else {}
                out = annotate(frame, dets, i, current)
                writer.write(out)
                sidecar.write(json.dumps({"frame": i, "detections": [asdict(d) for d in dets]}) + "\n")
                stats.record(i, current, unique)
                if stats.processed_frames % 100 == 0:
                    log.info("Progress: %d/%d frames", stats.processed_frames, meta.frame_count)
                yield FrameResult(i, out, dets, current, unique, stats)
    finally:
        if reset:
            reset()
    log.info("Done: %d frames, %.1fs, output=%s", stats.processed_frames, stats.elapsed, dst)
    log.info("Unique tracked objects: %s", unique)
