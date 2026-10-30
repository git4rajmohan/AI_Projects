Languages: **English** | [日本語](README.ja.md)

# VisionFlow — AI Video Object Detection, Tracking & Counting

**From video frames to counted, tracked objects.**

[Portfolio](../../README.md) | [User guide](VisionFlow_Userguide.html)

VisionFlow runs an uploaded video through an Ultralytics YOLO11 detector, follows objects across frames with persistent track IDs (ByteTrack or BoT-SORT), and counts them two separate ways: **current** (visible in this frame) and **unique** (distinct track IDs seen over the run). Detections are never summed per frame — a car in 40 frames is one car, not 40.

## Demo Video

[![yoloTrafficVechileCounterDemoVideo](https://img.youtube.com/vi/32d_BhMKsZw/0.jpg)]([https://youtu.be/32d_BhMKsZw)

## Why this project exists

Ask someone to "count the cars in an hour of traffic video" and they double-count the same car that appears in many frames. The naive script fix — adding up per-frame detections — is worse: the same car gets counted 40 times. What you actually need is a counter that knows which detections belong to the same physical object. VisionFlow is that counter: the detector finds things, the tracker gives them an identity, and the counter only believes the identity.

## What it demonstrates

- Streaming pipeline — one frame at a time from upload to annotated output; the whole video is never in RAM, so a long video processes like a short one.
- Detection → tracking → counting separation: YOLO detects, ByteTrack/BoT-SORT maintains identity across frames, counters treat per-frame presence and cumulative distinct objects as two different metrics.
- Persistent track IDs on annotated frames, rendered as `CAR #12 0.87` labels with a live counts HUD.
- A `.jsonl` sidecar per run — one line per output frame with its detections — replayed verbatim by the frame viewer, so a run is auditable without re-running the model.
- Swappable seams: the tracker sits behind a two-method interface (`update`/`reset`), so changing the tracker is one new class and nothing else edits.
- Typed errors (`VideoValidationError`, `ModelError`, `TrackerError`, `VideoWriteError`) with one-sentence UI messages; technical details stay in the log.

## Architecture

```text
Upload (.mp4/.avi/.mov/.mkv) -> validate + metadata
  -> YOLO detect/track (per frame, streamed)
  -> filter (confidence, classes, min box area)
  -> counter (current + unique via track IDs)
  -> annotator (boxes, CLASS #ID conf, counts HUD)
  -> annotated video + .jsonl sidecar
  -> dashboard: stats, count tables, charts, frame viewer
```

Every concept owns one module; `process_video()` composes them as a generator and releases reader, writer and tracker even when a run is aborted. See [docs/architecture.md](docs/architecture.md).

**Stack:** Python 3.11+ · Streamlit · Ultralytics YOLO11 (n/s/m) · OpenCV · ByteTrack / BoT-SORT · NumPy · Pandas · pytest

## Run locally (Windows PowerShell)

From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Optional GPU: force the CUDA PyTorch build (pip may claim the CPU wheel is fine):
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install "setuptools<82"
.\.venv\Scripts\streamlit.exe run app.py
# -> http://localhost:8501
```

Optional `ffmpeg` on PATH re-encodes the output to H.264 so it plays in the browser; without it the download still works. The first run downloads the YOLO weights automatically.

### Five-minute walkthrough

1. Upload a video in the sidebar; the validation card shows resolution, FPS and frame count.
2. Pick the model, thresholds and classes; press **Start Processing**.
3. Watch the live frame, stats and the two count tables (Current / Unique) update.
4. Watch or download the annotated video; review the count charts.
5. Step through any frame in the frame viewer and check its exact recorded detections.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `MODEL_NAME` | `yolo11n.pt` | Ultralytics weights file |
| `CONFIDENCE_THRESHOLD` | `0.50` | Initial confidence slider value |
| `IOU_THRESHOLD` | `0.50` | Initial IoU slider value |
| `DEVICE` | `auto` | `auto` (CUDA if available, else CPU), `cpu`, or `cuda` |
| `TRACKER` | `bytetrack` | `bytetrack` or `botsort` |
| `OUTPUT_DIR` | `data/output` | Where annotated videos and sidecars are written |

`OLLAMA_*` variables are reserved for a post-MVP LLM insights layer; the MVP does not use an LLM for detection or counting.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

50 tests, verified passing on the published copy. The suite is offline: no GPU, no model download, no internet. It covers counting (current vs unique), deduplication, class separation, annotation labels, video validation, writer cleanup, frame-skip mapping and the frame viewer.

## Limitations

- Track IDs are only stable within one run; they reset between runs.
- Unique counts can overcount if the tracker loses and re-acquires an object under occlusion or low confidence. Line-crossing counting (post-MVP) is the deliberate fix and is not bolted on yet.
- Frame skip speeds processing but makes ID breaks and overcounts more likely; the app warns on-screen.

## Credentials and safety

- Only a placeholder-key template is published (`.env.example`); the real `.env` is git-ignored and excluded from this copy.
- Only process video you are authorized to use. Do not use this tool to bypass authentication, access controls or stream restrictions, and respect privacy and local law when analysing footage of people.

## Project layout

| Path | Purpose |
|---|---|
| [app.py](app.py) | Streamlit page wiring |
| [config](config) / [models](models) | Settings, YOLO model manager |
| [detection](detection) / [tracking](tracking) / [counting](counting) | Detection dataclass + filters, tracker interface + state, counters + stats |
| [video](video) / [visualization](visualization) | Reader, writer, pipeline; annotator, dashboard, frame viewer |
| [tests](tests) | Offline pytest suite |
| [docs/architecture.md](docs/architecture.md) | Pipeline diagram and module responsibilities |
| [VisionFlow_Userguide.html](VisionFlow_Userguide.html) | Standalone illustrated guide; download and open in a browser |
