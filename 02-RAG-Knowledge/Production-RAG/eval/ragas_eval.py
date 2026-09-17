"""
Phase 2 — Ragas batch scoring (LLM-judged, offline).

Scores one Phase-1 runner pass with Ragas:

  Faithfulness        does every claim in the answer follow from the
                      retrieved contexts?          (LLM judge)
  ContextPrecision    are the relevant chunks ranked high in the retrieved
                      list?                          (LLM judge)
  ContextRecall       does the retrieved context cover everything the
                      reference answer needs?        (LLM judge)
  AnswerRelevancy     is the answer on-topic for the question?
                                                     (embedding based)

All LLM-judged metrics run through ONE judge model — a ChatOpenAI pointed at
an OpenAI-compatible endpoint (Ollama Cloud `gpt-oss:20b` by default) wrapped
in ragas' LangchainLLMWrapper, temperature 0.

AnswerRelevancy embeds the answer/question with an OpenAIEmbeddings client
(local Ollama `nomic-embed-text` by default).

Robustness: Ollama-hosted models' JSON output can trip Ragas' parsers. Mitigations:
  * RunConfig(timeout=max_wait, max_retries=2, max_wait=30, max_workers=1) —
    sequential judging (concurrency crashes on Windows, see _run_ragas).
  * nest_asyncio-free event loop handling: score_snapshot() runs in a FastAPI
    threadpool thread with NO running loop, so ragas' asyncio.run() creates a
    fresh loop there. (nest_asyncio + Windows Proactor + worker threads
    corrupts loop handles → "Cancelling an overlapped future failed".)
  * Configurable metrics list + judge model swap (e.g. glm-5.2) if a judge
    breaks — the runner falls back to the remaining metrics per question, so
    one bad row never kills the suite.
  * Every metric is scored per-question; failures yield null rows (not
    exceptions), so the snapshot always stays valid JSON.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, List, Optional

from eval.runner import SuiteCancelled  # noqa: E402  (shared exception)

DEFAULT_JUDGE_MODEL = "glm-5.3-flash"
# Ollama Cloud chat endpoint. NOTE: langchain's ChatOpenAI does NOT append
# /v1 — it posts to {base_url}/chat/completions as-is, so the /v1 must be in
# the URL (a bare-host default 404s into Ollama's HTML page and ragas reports
# NaN scores with raise_exceptions=False).
DEFAULT_JUDGE_BASE_URL = "https://ollama.com/v1"
# Local Ollama embeddings (same /v1 rule as above for OpenAIEmbeddings).
DEFAULT_EMBED_BASE_URL = "http://localhost:11434/v1"

ALL_METRICS = ["faithfulness", "context_precision", "context_recall", "answer_relevancy"]
DEFAULT_METRICS = ["faithfulness", "context_precision", "context_recall"]

# Metrics that need an LLM judge vs. only embeddings (used for fallback logic
# when no judge endpoint is reachable).
LLM_METRICS = {"faithfulness", "context_precision", "context_recall"}


def _api_key() -> str:
    return os.getenv("OLLAMA_API_KEY") or "ollama"


def _judge_alive(judge_model: str, judge_base_url: str, timeout: int, log=print) -> bool:
    """Circuit breaker: one tiny call before the batch. A congested cloud used to
    burn 17 questions × timeout × retries ≈ 2 hours producing all-null scores;
    failing fast here turns that into a 3-second skip."""
    from openai import OpenAI
    try:
        c = OpenAI(base_url=judge_base_url, api_key=_api_key(), timeout=timeout)
        c.chat.completions.create(model=judge_model, temperature=0, max_tokens=10,
                                  messages=[{"role": "user", "content": "Reply with: OK"}])
        return True
    except Exception as exc:
        log(f"  ragas: judge '{judge_model}' not reachable ({type(exc).__name__}) — "
            "skipping the whole ragas pass. Re-run when the cloud is healthy "
            "or switch judge_model (e.g. glm-5.2).")
        return False


def score_snapshot(snapshot: Dict[str, Any],
                   judge_model: str = DEFAULT_JUDGE_MODEL,
                   judge_base_url: str = DEFAULT_JUDGE_BASE_URL,
                   embed_model: str = "nomic-embed-text",
                   embed_base_url: str = DEFAULT_EMBED_BASE_URL,
                   metrics_list: Optional[List[str]] = None,
                   max_workers: int = 2,
                   max_wait: int = 300,
                   log=print,
                   progress_cb=None,
                   cancel_check=None) -> Dict[str, Any]:
    """
    Ragas-score a Phase-1 snapshot dict in place.

    Reads from each result row: question, answer_preview, retrieved_chunks
    (ranked order — Ragas needs contexts in the order the retriever emitted
    them), reference_answer via question id lookup in the golden set.

    Returns the "ragas" block to merge into the snapshot:
    {
      "judge_model": ..., "embed_model": ..., "metrics": [...],
      "elapsed_ms": ..., "errors": [...],
      "aggregate": {metric: mean | null, ...},
      "per_question": [{id, metric: score|null, failed: bool}, ...]
    }
    """
    t0 = time.perf_counter()
    wanted = [m for m in (metrics_list or DEFAULT_METRICS) if m in ALL_METRICS]
    if not wanted:
        raise ValueError(f"No valid ragas metrics in {metrics_list}")

    # The snapshot rows do not carry reference_answer (only must terms were
    # kept) — re-pair rows with the golden set by question id.
    golden_by_id = _golden_by_id(snapshot)

    samples: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for row in snapshot.get("results", []):
        if row.get("kind") == "negative":
            skipped.append(f"{row.get('id')}: negative case — refusal, not judged")
            continue  # refusal cases have no meaningful reference to judge
        if row.get("error"):
            skipped.append(f"{row.get('id')}: pipeline error row")
            continue
        answer = row.get("answer_preview") or ""
        # answer_preview is truncated at 400 chars in Phase 1 — score what we
        # have; note the truncation in errors so scores are interpretable.
        if not answer.strip():
            skipped.append(f"{row.get('id')}: empty answer")
            continue
        contexts = [c.get("preview", "") for c in row.get("retrieved_chunks", [])]
        if not contexts:
            skipped.append(f"{row.get('id')}: no retrieved chunks")
            continue
        g = golden_by_id.get(row.get("id"))
        if g is None and row.get("question"):
            g = _golden_by_question(snapshot, row["question"])
        reference = (g or {}).get("reference_answer", "")
        samples.append({
            "user_input": row.get("question", ""),
            "retrieved_contexts": contexts,
            "response": answer,
            "reference": reference,
            "row_id": row.get("id"),
        })

    if not samples:
        return _result_block(wanted, judge_model, embed_model,
                             t0, errors=["no scorable rows"], per_question=[])

    errors: List[str] = []
    if any(not s["reference"].strip() for s in samples):
        missing = [s["row_id"] for s in samples if not s["reference"].strip()]
        errors.append(f"reference_answer missing for {len(missing)} rows "
                      f"({', '.join(missing[:5])}...) — context_recall degraded")

    scores: Dict[str, Dict[str, Optional[float]]] = {}
    if progress_cb:
        progress_cb(0, len(samples))
    # Circuit breaker: skip the batch entirely when the judge endpoint is dead
    # or the user already pressed Stop.
    if cancel_check and cancel_check():
        raise SuiteCancelled("stopped by user")
    if not _judge_alive(judge_model, judge_base_url, max_wait, log):
        return _result_block(wanted, judge_model, embed_model, t0,
                             errors=["judge unreachable at batch start — ragas pass skipped "
                                     "(circuit breaker; was previously burning the full "
                                     "timeout×retries per question)"],
                             per_question=[], skipped=skipped)
    # ragas evaluate() historically was ONE opaque batch call with no
    # cancellation hook. It now runs DIRECTLY in this thread (a FastAPI
    # threadpool thread with no running event loop — ragas' asyncio.run()
    # creates a fresh Proactor loop here), question by question inside
    # _run_ragas: Stop aborts between questions (~within one judge call),
    # and the UI pill gets real per-question progress.
    try:
        scores = _run_ragas(samples, wanted, judge_model, judge_base_url,
                            embed_model, embed_base_url, max_workers,
                            max_wait, log, progress_cb, cancel_check)
    except SuiteCancelled:
        raise
    except Exception as exc:
        # Whole-batch failure (judge JSON collapse, timeout...): record and
        # retry once with judge fallback model if provided.
        errors.append(f"ragas evaluate failed: {type(exc).__name__}: {exc}")
        fallback_model = os.getenv("RAGAS_JUDGE_FALLBACK", "")
        if fallback_model and fallback_model != judge_model:
            log(f"  ragas: retrying with fallback judge '{fallback_model}'")
            try:
                scores = _run_ragas(samples, wanted, fallback_model,
                                    judge_base_url, embed_model, embed_base_url,
                                    max_workers, max_wait, log, progress_cb,
                                    cancel_check)
                judge_model = fallback_model
                errors.append(f"recovered with fallback judge '{fallback_model}'")
            except Exception as exc2:
                errors.append(f"fallback judge also failed: {type(exc2).__name__}: {exc2}")
        else:
            scores = {}

    per_question: List[Dict[str, Any]] = []
    failed_metrics = 0
    for s in samples:
        rid = s["row_id"]
        row_scores = scores.get(rid, {})
        n_null = sum(1 for m in wanted if row_scores.get(m) is None)
        if n_null == len(wanted) and wanted:
            failed_metrics += 1
        per_question.append({
            "id": rid,
            **{m: row_scores.get(m) for m in wanted},
            "failed": bool(wanted) and n_null == len(wanted),
        })
    if failed_metrics:
        errors.append(f"{failed_metrics}/{len(samples)} questions failed ALL "
                      f"their metric calls (judge JSON/model issues) — "
                      "consider a different judge model, e.g. glm-5.3-flash")

    block = _result_block(wanted, judge_model, embed_model, t0, errors,
                          per_question, skipped)
    return block


def _result_block(metrics_list: List[str], judge_model: str, embed_model: str,
                  t0: float, errors: List[str], per_question: List[Dict[str, Any]],
                  skipped: List[str] = None) -> Dict[str, Any]:
    skipped = skipped or []
    agg: Dict[str, Any] = {}
    for m in metrics_list:
        vals = [pq.get(m) for pq in per_question if pq.get(m) is not None]
        agg[m] = round(sum(vals) / len(vals), 4) if vals else None
    return {
        "judge_model": judge_model,
        "embed_model": embed_model,
        "metrics": metrics_list,
        "aggregate": agg,
        "per_question": per_question,
        "n_scored": len(per_question),
        "n_skipped": len(skipped),
        "skipped": skipped,
        "errors": errors,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def _run_ragas(samples: List[Dict[str, Any]], wanted: List[str],
               judge_model: str, judge_base_url: str,
               embed_model: str, embed_base_url: str,
               max_workers: int, max_wait: int, log=print,
               progress_cb=None, cancel_check=None) -> Dict[str, Dict[str, Optional[float]]]:
    """Score samples ONE AT A TIME — each via its own fresh evaluate() call.

    Why not one batch evaluate() over all samples?
      1. ragas 0.2.6's batch evaluate() has no cancellation hook — the
         per-question loop lets a user Stop abort between questions.
      2. Batch only reported progress 0/N → N/N; the loop gives the UI pill
         real per-question updates.
      3. Each evaluate() creates a fresh event loop with FRESH langchain
         clients (clients cache async httpx state bound to the loop that
         first used them). This sidesteps the Windows Proactor corruption
         ("Cancelling an overlapped future failed / handle is invalid") that
         nest_asyncio + worker threads + reused clients triggered.

    Cost: ~1-2 s/question of ragas init overhead — negligible next to judge
    latency. One crashed question nulls just that row instead of poisoning
    the whole batch.
    """
    from datasets import Dataset
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import RunConfig, evaluate
    from ragas.dataset_schema import EvaluationDataset
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    log(f"  ragas: judging {len(samples)} answers with {judge_model} "
        f"({', '.join(wanted)}), one question at a time")

    def _fresh_metrics():
        # Fresh wrappers + clients per question (see docstring point 3).
        judge_llm = LangchainLLMWrapper(
            ChatOpenAI(
                model=judge_model,
                temperature=0,
                api_key=_api_key(),
                base_url=judge_base_url,
                timeout=max_wait,
                max_retries=2,
            )
        )
        metric_objs = []
        for m in wanted:
            if m == "faithfulness":
                metric_objs.append(Faithfulness(llm=judge_llm))
            elif m == "context_precision":
                metric_objs.append(ContextPrecision(llm=judge_llm))
            elif m == "context_recall":
                metric_objs.append(ContextRecall(llm=judge_llm))
            elif m == "answer_relevancy":
                embedder = LangchainEmbeddingsWrapper(
                    OpenAIEmbeddings(
                        model=embed_model,
                        api_key=_api_key(),
                        base_url=embed_base_url,
                        timeout=max_wait,
                        chunk_size=16,
                    )
                )
                metric_objs.append(AnswerRelevancy(llm=judge_llm, embeddings=embedder))
        return metric_objs

    run_cfg = RunConfig(
        # RunConfig.timeout = PER-LLM-CALL timeout (not batch). Judge calls
        # get the full judge budget; max_retries=2 + modest backoff so a dead
        # endpoint fails in ~minutes instead of retry-looping for 7+ minutes.
        # max_workers is FORCED to 1: ragas' concurrent gather crashes on
        # Windows Proactor loops ("Cancelling an overlapped future failed /
        # handle is invalid"), and it also multiplied judge congestion.
        # Sequential judging: 17 q × 3 metrics × ~3 s ≈ 3-5 min.
        timeout=max_wait,
        max_retries=2,
        max_wait=30,
        max_workers=1,
        exception_types=(Exception,),
    )

    out: Dict[str, Dict[str, Optional[float]]] = {}
    for i, s in enumerate(samples):
        if cancel_check and cancel_check():
            raise SuiteCancelled("stopped by user")
        if progress_cb:
            progress_cb(i, len(samples))
        ds = Dataset.from_list([
            {
                "user_input": s["user_input"],
                "retrieved_contexts": s["retrieved_contexts"],
                "response": s["response"],
                "reference": s["reference"],
            }
        ])
        try:
            result = evaluate(dataset=EvaluationDataset.from_list(ds.to_list()),
                              metrics=_fresh_metrics(),
                              run_config=run_cfg,
                              show_progress=False,
                              raise_exceptions=False)
            out.update(_scores_by_row(result, [s]))
        except Exception as exc:
            # One crashed question nulls only its own row — never the batch.
            log(f"  ragas: '{s['row_id']}' evaluate crashed: "
                f"{type(exc).__name__}: {exc}")
            out[s["row_id"]] = {m: None for m in wanted}
    if progress_cb:
        progress_cb(len(samples), len(samples))
    return out


def _scores_by_row(result: Any, samples: List[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[float]]]:
    """
    ragas 0.2.6: evaluate() returns an EvaluationDataset whose .samples list
    mirrors the input order; each sample's .scores dict is
    {metric_name: float|None}. Map by index back to our row ids.
    """
    out: Dict[str, Dict[str, Optional[float]]] = {}
    try:
        eval_samples = list(result.samples)  # EvaluationDataset
    except AttributeError:
        eval_samples = []
        try:
            # Fallback: pandas DataFrame with one row per input sample.
            df = result.to_pandas()
            for i in range(len(df)):
                eval_samples.append(df.iloc[i])
        except Exception:
            eval_samples = []

    for i, s in enumerate(samples):
        row: Dict[str, Optional[float]] = {}
        if i < len(eval_samples):
            es = eval_samples[i]
            raw = getattr(es, "scores", None)
            if raw is None and hasattr(es, "get"):
                raw = {k: es.get(k) for k in
                       ("faithfulness", "context_precision", "context_recall",
                        "answer_relevancy") if es.get(k) is not None}
            for m in ("faithfulness", "context_precision", "context_recall",
                      "answer_relevancy"):
                v = (raw or {}).get(m) if isinstance(raw, dict) else None
                if v is None and hasattr(es, "get"):
                    try:
                        v = es.get(m)
                    except Exception:
                        v = None
                if isinstance(v, (int, float)) and math.isfinite(float(v)):
                    row[m] = round(float(v), 4)
                else:
                    # NaN/None = the judge call failed for this metric (ragas
                    # writes NaN instead of raising when raise_exceptions=False)
                    row[m] = None
        out[s["row_id"]] = row
    return out


def _golden_by_id(snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Golden items paired with the snapshot rows. The snapshot itself doesn't
    carry reference_answer, so read the frozen file when available.
    """
    if snapshot.get("_golden_ref"):  # runner-injected map (preferred)
        return snapshot["_golden_ref"]
    try:
        from eval.golden_generator import load_frozen
        return {g.get("id"): g for g in load_frozen() or []}
    except Exception:
        return {}


def _golden_by_question(snapshot: Dict[str, Any], question: str) -> Dict[str, Any]:
    gmap = _golden_by_id(snapshot)
    for g in gmap.values():
        if (g.get("question") or "").strip() == question.strip():
            return g
    return {}


def format_ragas_summary(block: Dict[str, Any]) -> str:
    """One-line log summary of a ragas block."""
    if not block:
        return "ragas: (not run)"
    agg = block.get("aggregate", {})
    parts = [f"{m}={agg.get(m)}" for m in block.get("metrics", [])]
    errs = f", {len(block.get('errors', []))} errors" if block.get("errors") else ""
    return f"ragas[{block.get('judge_model')}]: {', '.join(parts)}{errs}"