"""
FastAPI server for the RAG pipeline visualizer UI.

Serves the static SPA from ui/static and exposes the JSON API:
  GET    /api/config                 -> param metadata + current values
  POST   /api/config                 -> save values (persist ui_config.json)
  POST   /api/config/reset           -> reset to defaults
  GET    /api/browse?path=           -> server-side file browser (project-root relative)
  GET    /api/docs                   -> default docs/ folder listing
  GET    /api/collection/status      -> chunk count + doc ids
  DELETE /api/collection             -> clear the collection
  POST   /api/ingest/start           -> new ingestion run {files}
  POST   /api/ingest/step            -> run one ingest step {run_id, step_index}
  POST   /api/query/start            -> new query run {query}
  POST   /api/query/step             -> run one query step {run_id, step_index}
  POST   /api/runs/reset             -> drop a run from memory
  POST   /api/suite/start            -> new regression-suite run (Phase 1)
  POST   /api/suite/step             -> run one suite step {run_id, step_index}
  GET    /api/eval/snapshots         -> snapshot summaries + current baseline
  GET    /api/eval/snapshot/{id}     -> full snapshot (per-question rows)
  DELETE /api/eval/snapshot/{id}     -> delete a snapshot
  POST   /api/eval/baseline          -> store a snapshot as the regression baseline
  GET    /api/eval/diff?id=...       -> gate diff vs baseline (or ?against=<id>)
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import chromadb

from ui import runners
from ui.config_store import (
    PARAM_META,
    default_values,
    load_values,
    reset_values,
    save_values,
)

app = FastAPI(title="RAG Pipeline Visualizer")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    from fastapi.responses import FileResponse
    return FileResponse(STATIC_DIR / "index.html")


# ────────────────────────── config ──────────────────────────

@app.get("/api/config")
def get_config():
    return {
        "meta": PARAM_META,
        "values": load_values(),
        "steps": __import__("ui.config_store", fromlist=["STEP_DEFS"]).STEP_DEFS,
    }


@app.post("/api/config")
def post_config(values: dict):
    try:
        return {"values": save_values(values)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/config/reset")
def post_config_reset():
    return {"values": reset_values()}


# ────────────────────────── file browser ──────────────────────────

@app.get("/api/browse")
def browse(path: str = ""):
    try:
        return runners.browse_files(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/docs")
def default_docs():
    return {"files": runners.list_docs()}


# ────────────────────────── collection management ──────────────────────────

def _client() -> "chromadb.api.ClientAPI":
    from config.settings import CHROMA_PATH
    return chromadb.PersistentClient(path=CHROMA_PATH)


@app.get("/api/debug/imports")
def debug_imports():
    """Which interpreter is serving, and can it import the eval stack?"""
    import sys
    out = {"executable": sys.executable, "python": sys.version.split()[0],
           "pythonpath": sys.path[:6]}
    for mod in ("chromadb", "ragas", "langchain_community"):
        try:
            __import__(mod)
            out[mod] = "ok"
        except Exception as exc:
            out[mod] = f"FAIL: {type(exc).__name__}: {exc}"
    # the REAL import eval.runner does at module load (guarded there)
    try:
        from eval import ragas_eval as re_
        out["eval_runner_ragas"] = f"ok (judge={re_.DEFAULT_JUDGE_MODEL})"
    except Exception as exc:
        out["eval_runner_ragas"] = f"FAIL: {type(exc).__name__}: {exc}"
    # package versions + file locations (system vs venv site-packages ordering)
    for pkg in ("langchain_openai", "langchain_core", "ragas"):
        try:
            mod = __import__(pkg)
            out[f"{pkg}.version"] = getattr(mod, "__version__", "?")
            out[f"{pkg}.file"] = getattr(mod, "__file__", "?")
        except Exception as exc:
            out[f"{pkg}.version"] = f"FAIL: {type(exc).__name__}: {exc}"
    return out


@app.get("/api/collection/status")
def collection_status(chroma_path: str | None = None, collection_name: str | None = None):
    from config.settings import CHROMA_PATH, COLLECTION_NAME
    cp = chroma_path or CHROMA_PATH
    cn = collection_name or COLLECTION_NAME
    try:
        client = chromadb.PersistentClient(path=cp)
        try:
            col = client.get_collection(name=cn)
        except Exception:
            return {"exists": False, "count": 0, "chroma_path": cp, "collection_name": cn}
        metas = col.get(include=["metadatas"]) if col.count() else None
        docs: dict[str, int] = {}
        if metas:
            for m in metas["metadatas"]:
                dt = m.get("doc_title", "?")
                docs[dt] = docs.get(dt, 0) + 1
        return {"exists": True, "count": col.count(), "documents": docs,
                "chroma_path": cp, "collection_name": cn}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/collection")
def delete_collection(chroma_path: str | None = None, collection_name: str | None = None):
    from config.settings import CHROMA_PATH, COLLECTION_NAME
    cp = chroma_path or CHROMA_PATH
    cn = collection_name or COLLECTION_NAME
    try:
        client = chromadb.PersistentClient(path=cp)
        client.delete_collection(cn)
        return {"ok": True, "chroma_path": cp, "collection_name": cn}
    except Exception as exc:
        raise HTTPException(status_code=404 if "does not exist" in str(exc).lower() else 500,
                            detail=str(exc))


# ────────────────────────── runs ──────────────────────────

@app.post("/api/ingest/start")
def ingest_start(payload: dict):
    from ui.config_store import load_values
    from ui import runners
    config = payload.get("config") or load_values()["ingest"]
    files = payload.get("files") or []
    if not files:
        raise HTTPException(status_code=400, detail="No files selected")
    return runners.start_run("ingest", config, {"files": files})


@app.post("/api/ingest/step")
def ingest_step(payload: dict):
    run = runners.get_run(payload.get("run_id", ""))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    idx = int(payload.get("step_index", 0))
    return runners.ingest_step(run, idx)


@app.post("/api/query/start")
def query_start(payload: dict):
    from ui.config_store import load_values
    from ui import runners
    values = load_values()
    config = payload.get("config") or values["query"]
    # The query pipeline reads the collection that ingestion wrote: inject the
    # ingest-side store config (chroma_path / collection_name) into the run.
    config = dict(config)
    config["store"] = values["ingest"]["store"]
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is empty")
    return runners.start_run("query", config, {"query": query})


@app.post("/api/query/step")
def query_step(payload: dict):
    run = runners.get_run(payload.get("run_id", ""))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    idx = int(payload.get("step_index", 0))
    return runners.query_step(run, idx)


@app.post("/api/runs/reset")
def runs_reset(payload: dict):
    runners.reset_run(payload.get("run_id", ""))
    return {"ok": True}


# ────────────────────────── evaluation (Phase 0) ──────────────────────────

@app.get("/api/eval/golden")
def eval_golden_list():
    from eval import golden_generator
    items = golden_generator.load_frozen()
    return {"frozen": items, "path": str(golden_generator._golden_path()),
            "exists": bool(items)}


@app.post("/api/eval/start")
def eval_start(payload: dict):
    from ui.config_store import load_values
    from ui import runners
    config = payload.get("config") or load_values().get("eval", {})
    return runners.start_run("eval", config, {})


@app.post("/api/eval/step")
def eval_step(payload: dict):
    run = runners.get_run(payload.get("run_id", ""))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    idx = int(payload.get("step_index", 0))
    return runners.eval_step(run, idx)


@app.post("/api/eval/golden/freeze")
def eval_golden_freeze(payload: dict):
    """Freeze checked items; falls back to the run's pending kept candidates."""
    from eval import golden_generator
    approved = payload.get("approved", [])
    if not approved:
        run = runners.get_run(payload.get("run_id", ""))
        if run:
            approved = run["state"].get("pending_freeze", [])
    try:
        return golden_generator.freeze(approved)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ────────────────────────── suite runs (Phase 1) ──────────────────────────

@app.post("/api/suite/start")
def suite_start(payload: dict):
    from ui.config_store import load_values
    config = payload.get("config") or load_values().get("suite", {})
    return runners.start_run("suite", config, {})


@app.post("/api/suite/step")
def suite_step(payload: dict):
    run = runners.get_run(payload.get("run_id", ""))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    idx = int(payload.get("step_index", 0))
    return runners.suite_step(run, idx)


@app.get("/api/suite/progress")
def suite_progress(run_id: str):
    """Live progress for a running suite (phase, question i/n, elapsed)."""
    from eval import runner
    p = runner.PROGRESS.get(run_id)
    return {"run_id": run_id, "progress": p}  # progress null when finished


@app.post("/api/suite/stop")
def suite_stop(payload: dict):
    """User pressed Stop: flag the run so the long step aborts at the next
    question boundary (or within ~2 s during the ragas judge batch)."""
    from eval import runner
    run_id = payload.get("run_id", "")
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id required")
    runner.cancel_run(run_id)
    return {"ok": True, "run_id": run_id, "cancelled": True}


@app.get("/api/eval/snapshots")
def eval_snapshots():
    from eval import runner
    return {"snapshots": runner.list_snapshots(),
            "baseline": runner.get_baseline()}


@app.get("/api/eval/snapshot/{snapshot_id}")
def eval_snapshot_detail(snapshot_id: str):
    from eval import runner
    snap = runner.load_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snap


@app.post("/api/eval/baseline")
def eval_set_baseline(payload: dict):
    from eval import runner
    sid = payload.get("snapshot_id", "")
    try:
        return {"baseline": runner.set_baseline(sid)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/eval/snapshot/{snapshot_id}")
def eval_delete_snapshot(snapshot_id: str):
    from eval import runner
    if not runner.delete_snapshot(snapshot_id):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"ok": True}


@app.get("/api/eval/diff")
def eval_diff(id: str, against: str | None = None):
    """Diff a snapshot against the baseline (or `against` snapshot)."""
    from eval import gate
    try:
        return gate.evaluate(id, against)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ────────────────────────── error handler ──────────────────────────

@app.exception_handler(Exception)
def unhandled_exception(request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


# Static SPA fallback for anything not API/static (no client-side routing needed,
# single index.html).
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="spa")