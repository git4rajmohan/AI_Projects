"""
Phase 1 — evaluation runner.

Loops every frozen golden question through the existing pipeline pieces
(hybrid/semantic retrieval -> build_prompt -> generate) for ONE config combo
(chunking strategy + retriever + top_k), scores it with the deterministic
metrics from eval/metrics.py, and writes a snapshot JSON into eval/snapshots/.

Snapshot shape
--------------
{
  "snapshot_id": "a1b2c3d4",
  "created_at": "2026-09-11T12:00:00",
  "config": {"strategy": "structural", "retriever": "hybrid", "top_k": 5,
              "overfetch_factor": 2, "rrf_k": 60, "collection_name": "rag_docs"},
  "corpus_size": 61,
  "golden_count": 15,
  "aggregate": {...from metrics.aggregate()...},
  "results": [ {per-question metric row + answer preview, citations,
                retrieved chunks, missing must terms}, ... ],
  "elapsed_ms": 123456
}

The chunking strategy matters here: retrieval always reads from the ChromaDB
collection that ingestion populated. If the frozen golden set was generated
against a corpus ingested with strategy X but the collection currently holds
strategy Y chunks, section_title matching degrades (only exact header matches
count). The runner reports the dominant strategy of the live corpus in
`config.corpus_strategy` so a mismatch is visible in the UI.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from generation.answer_generator import generate as llm_generate
from generation.prompt_builder import build_prompt
from retrieval import hybrid_search
from eval import metrics
EVAL_DIR = Path(__file__).resolve().parent
SNAPSHOT_DIR = EVAL_DIR / "snapshots"
BASELINE_FILE = EVAL_DIR / "BASELINE.json"

# Live progress for the currently-running suite, read by the UI poll endpoint.
# Key: run_id. Cleared when the suite finishes or fails.
PROGRESS: Dict[str, Dict[str, Any]] = {}

# run_ids the user asked to cancel. The long-running step checks this between
# questions (and ragas between metric batches) and aborts promptly.
CANCELLED: set = set()


class SuiteCancelled(Exception):
    """Raised inside run_suite when the user pressed Stop."""


def cancel_run(run_id: str) -> None:
    CANCELLED.add(run_id)


def is_cancelled(run_id: Optional[str]) -> bool:
    return bool(run_id) and run_id in CANCELLED


# Phase 2 — Ragas LLM-judged scoring. Imported HERE (after SuiteCancelled is
# defined) because eval.ragas_eval does `from eval.runner import SuiteCancelled`
# — importing it earlier creates a circular-import failure that the except
# silently swallowed, leaving ragas_eval=None and every run reporting
# "ragas not installed" even when it was installed.
try:
    from eval import ragas_eval
except Exception:  # pragma: no cover — ragas absent
    ragas_eval = None


def _set_progress(run_id: Optional[str], **fields: Any) -> None:
    """Update the live progress entry for a suite run (no-op without run_id)."""
    if not run_id:
        return
    entry = PROGRESS.setdefault(run_id, {"phase": "starting", "question_index": 0,
                                          "question_total": 0, "started_at": time.time()})
    entry.update(fields)
    entry["elapsed_s"] = int(time.time() - entry["started_at"])


def _dominant_strategy(collection) -> str:
    """Most common chunking strategy among stored chunks."""
    try:
        got = collection.get(include=["metadatas"], limit=500)
        counts = Counter(str(m.get("strategy", "?")) for m in got["metadatas"])
        return counts.most_common(1)[0][0] if counts else "?"
    except Exception:
        return "?"


def run_suite(
    golden: List[Dict[str, Any]],
    collection,
    embedder,
    chat_cfg: Dict[str, Any],
    retrieve_cfg: Dict[str, Any],
    strategy: str = "structural",
    augment_cfg: Optional[Dict[str, Any]] = None,
    log=print,
    include_ragas: bool = False,
    ragas_cfg: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute the golden set through the retrieval + generation pipeline once.

    chat_cfg:     {chat_model, chat_base_url, max_tokens, temperature}
    retrieve_cfg: {retriever, top_k, overfetch_factor, rrf_k}
    include_ragas: when True, additionally Ragas-score each answer with an
                   LLM judge (Phase 2) and merge the block into the snapshot
                   under "ragas". Off by default so cheap gates stay LLM-free.
    ragas_cfg:    {judge_model, judge_base_url, embed_model, embed_base_url,
                   metrics, max_workers, max_wait}
    """
    from openai import OpenAI

    chat_model = chat_cfg.get("chat_model", "gpt-oss:120b")
    chat_base_url = chat_cfg.get("chat_base_url", "")
    max_tokens = int(chat_cfg.get("max_tokens", 2048))
    temperature = chat_cfg.get("temperature", 1.0)
    client = OpenAI(base_url=chat_base_url, api_key=_api_key())

    retriever = retrieve_cfg.get("retriever", "hybrid")
    top_k = int(retrieve_cfg.get("top_k", 5))
    overfetch = int(retrieve_cfg.get("overfetch_factor", 2))
    rrf_k = int(retrieve_cfg.get("rrf_k", 60))
    system_prompt = (augment_cfg or {}).get("system_prompt") or None

    t_start = time.perf_counter()
    results: List[Dict[str, Any]] = []

    _set_progress(run_id, phase="generating", question_index=0,
                  question_total=len(golden))
    for i, item in enumerate(golden, start=1):
        if is_cancelled(run_id):
            raise SuiteCancelled("stopped by user")
        q = item.get("question", "")
        log(f"  [{i}/{len(golden)}] {q[:70]}")
        _set_progress(run_id, question_index=i, current_question=q[:80])
        try:
            row = _run_one(item, client, chat_model, chat_base_url, max_tokens,
                           temperature, collection, embedder, retriever, top_k,
                           overfetch, rrf_k, system_prompt, strategy)
        except Exception as exc:
            row = {
                "id": item.get("id"), "kind": item.get("kind"), "question": q,
                "strategy": strategy, "retriever": retriever,
                "error": f"{type(exc).__name__}: {exc}",
                "recall_at_k": None, "first_relevant_rank": None,
                "citation_coverage": None, "must_term_coverage": None,
                "refusal_correct": None, "retrieve_ms": 0, "generate_ms": 0,
                "total_ms": 0, "n_retrieved": 0, "n_citations": 0,
                "expected_sections": item.get("expected_sections", []),
                "matched_sections": [],
            }
        results.append(row)

    agg = metrics.aggregate(results)
    snapshot = {
        "snapshot_id": uuid.uuid4().hex[:8],
        "created_at": metrics.now_stamp(),
        "config": {
            "strategy": strategy,
            "retriever": retriever,
            "top_k": top_k,
            "overfetch_factor": overfetch,
            "rrf_k": rrf_k,
            "chat_model": chat_model,
            "embed_model": getattr(embedder, "name", "?"),
            "corpus_strategy": _dominant_strategy(collection),
            "corpus_size": collection.count(),
        },
        "golden_count": len(golden),
        "aggregate": agg,
        "results": results,
        "elapsed_ms": int((time.perf_counter() - t_start) * 1000),
    }

    # Phase 2: optional Ragas LLM-judge pass. Failures inside score_snapshot
    # degrade to null scores recorded in the ragas block's `errors` — the
    # deterministic snapshot is written either way.
    if include_ragas:
        if ragas_eval is None:
            snapshot["ragas"] = {"error": "ragas not installed "
                                         "(pip install ragas langchain-openai langchain-community datasets)"}
            log("  ragas: NOT AVAILABLE — skipped (deterministic snapshot written)")
        else:
            try:
                _set_progress(run_id, phase="ragas-judging", question_index=0,
                              question_total=len([r for r in results if r.get("kind") != "negative"]))
                # score_snapshot re-pairs rows with the frozen golden set for
                # reference answers; injecting the map avoids a second read.
                snapshot["_golden_ref"] = {g.get("id"): g for g in golden}
                rblock = ragas_eval.score_snapshot(
                    snapshot,
                    judge_model=(ragas_cfg or {}).get("judge_model",
                                                      ragas_eval.DEFAULT_JUDGE_MODEL),
                    judge_base_url=(ragas_cfg or {}).get("judge_base_url",
                                                          ragas_eval.DEFAULT_JUDGE_BASE_URL),
                    embed_model=(ragas_cfg or {}).get("embed_model", "nomic-embed-text"),
                    embed_base_url=(ragas_cfg or {}).get("embed_base_url",
                                                          ragas_eval.DEFAULT_EMBED_BASE_URL),
                    metrics_list=(ragas_cfg or {}).get("metrics") or None,
                    max_workers=int((ragas_cfg or {}).get("max_workers", 2)),
                    max_wait=int((ragas_cfg or {}).get("max_wait", 300)),
                    log=log,
                    progress_cb=lambda done, total: _set_progress(
                        run_id, question_index=done, question_total=total),
                    cancel_check=lambda: is_cancelled(run_id),
                )
                snapshot["ragas"] = rblock
                log("  " + ragas_eval.format_ragas_summary(rblock))
            except SuiteCancelled:
                raise  # propagate to suite_step — nothing persisted, run aborted
            except Exception as exc:
                snapshot["ragas"] = {"error": f"{type(exc).__name__}: {exc}"}
                log(f"  ragas: FAILED — {type(exc).__name__}: {exc} (deterministic snapshot kept)")
            finally:
                snapshot.pop("_golden_ref", None)  # never persist the map

    _set_progress(run_id, phase="done", question_index=len(golden),
                  question_total=len(golden))
    if run_id:
        PROGRESS.pop(run_id, None)  # finished — stop polling
        CANCELLED.discard(run_id)
    return snapshot


def _run_one(item, client, chat_model, chat_base_url, max_tokens, temperature,
             collection, embedder, retriever, top_k, overfetch, rrf_k,
             system_prompt, strategy) -> Dict[str, Any]:
    """One golden question end-to-end: retrieve -> prompt -> generate -> score."""
    q = item["question"]

    t0 = time.perf_counter()
    if retriever == "semantic":
        from retrieval import semantic_search
        chunks = semantic_search.search(q, collection, embedder, top_k)
        trace_meta = []
    else:
        traced = hybrid_search.search_with_trace(
            q, collection, embedder, top_k, rrf_k=rrf_k, overfetch_factor=overfetch)
        chunks = traced["final"]
        trace_meta = traced["trace"]["fused"]
    retrieve_ms = int((time.perf_counter() - t0) * 1000)

    retrieved_meta = [c.metadata for c in chunks]

    t0 = time.perf_counter()
    pm = build_prompt(q, chunks, system_prompt=system_prompt)

    # answer_generator.generate() builds its client from its own module
    # globals; patch them for this call so the UI-configured model/endpoint
    # are honored, then restore. (Same trick the golden generator uses.)
    import generation.answer_generator as ag
    from config.settings import CHAT_BASE_URL as _DEF_URL
    orig_model, orig_url = ag.CHAT_MODEL, ag.CHAT_BASE_URL
    ag.CHAT_MODEL = chat_model
    ag.CHAT_BASE_URL = chat_base_url or _DEF_URL
    try:
        answer = llm_generate(pm, q, len(chunks), max_tokens=max_tokens,
                              temperature=temperature if temperature is not None else None)
    finally:
        ag.CHAT_MODEL, ag.CHAT_BASE_URL = orig_model, orig_url
    generate_ms = int((time.perf_counter() - t0) * 1000)

    row = metrics.score_question(
        item, answer.text, retrieved_meta, retrieve_ms, generate_ms,
        strategy, retriever)
    row.update({
        "answer_preview": answer.text[:400],
        "citations": answer.citations,
        "retrieved_chunks": [
            {"rank": c.rank, "doc_title": c.metadata.get("doc_title", "?"),
             "section_title": c.metadata.get("section_title", ""),
             "score": round(c.score, 4),
             "matched": bool(metrics.section_match(c.metadata, item.get("expected_sections", []) or [])),
             "preview": c.content[:120].replace("\n", " ")}
            for c in chunks
        ],
        "trace": trace_meta[:top_k],
    })
    terms = metrics.extract_must_terms(item.get("reference_answer", ""))
    text_norm = (answer.text or "").lower()
    row["missing_terms"] = [t for t in terms if t not in text_norm]
    return row


def _api_key() -> str:
    import os
    return os.getenv("OLLAMA_API_KEY") or "ollama"


# ────────────────────────── snapshot persistence ──────────────────────────

def save_snapshot(snapshot: Dict[str, Any]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{snapshot['snapshot_id']}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_snapshots() -> List[Dict[str, Any]]:
    """Summaries (no per-question rows) newest-first (by created_at)."""
    if not SNAPSHOT_DIR.exists():
        return []
    out = []
    for p in SNAPSHOT_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "snapshot_id": data.get("snapshot_id"),
            "created_at": data.get("created_at"),
            "label": data.get("label"),
            "config": data.get("config", {}),
            "golden_count": data.get("golden_count"),
            "aggregate": data.get("aggregate", {}),
            "ragas": data.get("ragas", {}),
            "path": str(p),
        })
    out.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return out


def load_snapshot(snapshot_id: str) -> Optional[Dict[str, Any]]:
    path = SNAPSHOT_DIR / f"{snapshot_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def delete_snapshot(snapshot_id: str) -> bool:
    path = SNAPSHOT_DIR / f"{snapshot_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def set_baseline(snapshot_id: str) -> Dict[str, Any]:
    snap = load_snapshot(snapshot_id)
    if not snap:
        raise ValueError(f"Snapshot '{snapshot_id}' not found")
    BASELINE_FILE.write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "created_at": snap.get("created_at"),
        "config": snap.get("config", {}),
        "aggregate": snap.get("aggregate", {}),
        "golden_count": snap.get("golden_count"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_baseline()


def get_baseline() -> Optional[Dict[str, Any]]:
    if not BASELINE_FILE.exists():
        return None
    try:
        return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None