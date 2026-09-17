"""
Step-by-step runners for the UI.

Both the ingestion flow and the query flow are split into discrete steps.
Each step runs as a pure function of (config, state) -> partial state so the
frontend can drive them one at a time and visualize per-step results.

An in-memory RUNS store keeps per-run state between requests (single-user,
localhost server; state is lost on server restart, which is acceptable).
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from chunking.character_splitter import split_by_characters
from chunking.embedding_splitter import split_by_embeddings
from chunking.semantic_splitter import split_by_headers
from config.settings import (
    CHAR_CHUNK_OVERLAP,
    CHAR_CHUNK_SIZE,
    DOCS_PATH,
    SEMANTIC_MAX_WORDS,
)
from generation.answer_generator import generate
from generation.prompt_builder import build_prompt
from retrieval import hybrid_search
from retrieval.semantic_search import search as semantic_search
from ui.config_store import STEP_DEFS, default_values
from vectorstore.embedder import embed_chunks, load_embedding_model
from vectorstore.store import get_or_create_collection, load_collection, upsert_chunks

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RUNS: Dict[str, dict] = {}


# ────────────────────────── run lifecycle ──────────────────────────

def start_run(tab: str, config: Dict[str, Any], payload: Dict[str, Any]) -> dict:
    """Create a new run for a tab; returns run descriptor with step list."""
    run_id = uuid.uuid4().hex[:12]
    steps = [
        {"key": s["key"], "title": s["title"], "icon": s["icon"],
         "status": "idle", "duration_ms": None, "error": None}
        for s in STEP_DEFS[tab]
    ]
    RUNS[run_id] = {
        "id": run_id,
        "tab": tab,
        "config": config,
        "payload": payload,          # e.g. {"files": [...]} or {"query": "..."}
        "state": {},                 # intermediate data between steps
        "steps": steps,
        "results": {},               # step_key -> UI detail payload
        "created_at": time.time(),
    }
    return {"run_id": run_id, "steps": steps}


def get_run(run_id: str) -> Optional[dict]:
    return RUNS.get(run_id)


def _mark(run: dict, key: str, *, status: str, duration_ms: Optional[int] = None,
          error: Optional[str] = None, result: Any = None) -> None:
    for s in run["steps"]:
        if s["key"] == key:
            s["status"] = status
            s["duration_ms"] = duration_ms
            if error is not None:
                s["error"] = error
            break
    if result is not None:
        run["results"][key] = result


def reset_run(run_id: str) -> None:
    RUNS.pop(run_id, None)


# ────────────────────────── ingestion steps ──────────────────────────

def ingest_step(run: dict, step_index: int) -> dict:
    """Execute one ingestion step; returns {status, data} for the UI node."""
    cfg = run["config"]
    files: List[str] = run["payload"].get("files", [])
    state = run["state"]
    t0 = time.perf_counter()
    step = run["steps"][step_index]
    key = step["key"]

    try:
        if key == "load":
            docs: List[dict] = []
            for rel in files:
                path = (PROJECT_ROOT / rel).resolve()
                if not path.exists():
                    raise FileNotFoundError(f"Not found: {rel}")
                text = path.read_text(encoding=cfg["load"]["encoding"])
                docs.append({
                    "path": rel,
                    "title": os.path.basename(rel),
                    "chars": len(text),
                    "words": len(text.split()),
                    "text": text,
                })
            state["docs"] = docs
            result = {
                "files": [{k: v for k, v in d.items() if k != "text"} for d in docs],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "chunk":
            docs: List[dict] = state.get("docs")
            if not docs:
                raise RuntimeError("No documents loaded (run 'load' first)")
            c = cfg["chunk"]
            strategy = c["strategy"]
            # ui_config.json saved before the rename may still hold "semantic"
            # meaning the header-based splitter — map it to "structural".
            if strategy == "semantic" and "sem_percentile" not in c:
                strategy = "structural"
            all_chunks: List[Any] = []
            per_doc = []
            for d in docs:
                if strategy == "structural":
                    chunks = split_by_headers(d["text"], d["title"], int(c["semantic_max_words"]))
                elif strategy == "semantic":
                    model = load_embedding_model(cfg["embed"]["embed_model"])
                    model._client.base_url = cfg["embed"]["embed_base_url"]
                    chunks = split_by_embeddings(
                        d["text"], d["title"], model,
                        buffer_size=int(c.get("sem_buffer_size", 1)),
                        percentile_threshold=int(c.get("sem_percentile", 95)),
                        min_chunk_size=int(c.get("sem_min_chunk_size", 100)),
                    )
                else:
                    chunks = split_by_characters(
                        d["text"], d["title"],
                        int(c["char_chunk_size"]), int(c["char_chunk_overlap"]),
                    )
                all_chunks.extend(chunks)
                per_doc.append({
                    "title": d["title"],
                    "chunk_count": len(chunks),
                    "broken_code": sum(1 for ch in chunks if ch.has_code_block and ch.content.count("```") % 2 == 1),
                    "broken_table": sum(1 for ch in chunks if ch.has_table and not ch.content.rstrip().endswith("|")),
                })
            previews = [
                {
                    "doc_title": ch.metadata.get("doc_title", "?"),
                    "chunk_index": ch.metadata.get("chunk_index", 0),
                    "section_title": ch.metadata.get("section_title", ""),
                    "words": ch.word_count,
                    "has_code_block": ch.has_code_block,
                    "has_table": ch.has_table,
                    "preview": ch.content[:200],
                    "metadata": dict(ch.metadata),
                }
                for ch in all_chunks[:40]
            ]
            state["chunks"] = all_chunks
            result = {
                "strategy": strategy,
                "total_chunks": len(all_chunks),
                "per_doc": per_doc,
                "chunks": previews,
                "params": {k: c[k] for k in c if k != "strategy"} | {"strategy": strategy},
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "embed":
            chunks: List[Any] = state.get("chunks")
            if not chunks:
                raise RuntimeError("No chunks to embed (run 'chunk' first)")
            model = load_embedding_model(cfg["embed"]["embed_model"])
            # local ollama ignores the key; allow overriding base URL from UI
            model._client.base_url = cfg["embed"]["embed_base_url"]
            embeddings = embed_chunks(chunks, model)
            dims = len(embeddings[0]) if embeddings else 0
            state["embeddings"] = embeddings
            result = {
                "model": model.name,
                "endpoint": str(cfg["embed"]["embed_base_url"]),
                "chunks_embedded": len(chunks),
                "dimensions": dims,
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "store":
            chunks: List[Any] = state.get("chunks")
            embeddings: List[List[float]] = state.get("embeddings")
            if not chunks or embeddings is None:
                raise RuntimeError("Nothing to store (run 'embed' first)")
            s = cfg["store"]
            # Delete stale chunks of the selected docs before upserting so
            # re-ingestion doesn't leave orphaned chunks from a previous run.
            client_ids_to_delete: List[str] = []
            try:
                existing = load_collection(s["chroma_path"], s["collection_name"])
                doc_titles = {d["title"] for d in state["docs"]}
                got = existing.get(include=["metadatas"]) if existing.count() else None
                if got:
                    client_ids_to_delete = [
                        cid for cid, meta in zip(got["ids"], got["metadatas"])
                        if meta.get("doc_title") in doc_titles
                    ]
                if client_ids_to_delete:
                    existing.delete(ids=client_ids_to_delete)
            except RuntimeError:
                pass  # collection doesn't exist yet - first ingestion
            collection = get_or_create_collection(s["chroma_path"], s["collection_name"])
            upsert_chunks(collection, chunks, embeddings)
            total = collection.count()
            # What ChromaDB actually persists per chunk: id, raw text,
            # embedding vector, metadata. Show the first few stored rows so
            # students can see the "for every chunk the store keeps text +
            # vector + metadata" claim concretely.
            got = collection.get(
                include=["documents", "metadatas", "embeddings"],
                limit=5,
            )
            stored = []
            for cid, doc, meta, emb in zip(
                got["ids"], got["documents"], got["metadatas"], got["embeddings"]
            ):
                # embeddings come back as an (n, dim) numpy array; `emb` is one
                # row already (the full dim-vector for this chunk)
                emb_row = emb if emb is not None else []
                stored.append({
                    "id": cid,
                    "metadata": meta,
                    "embedding_preview": [round(float(x), 5) for x in emb_row[:8]],
                    "embedding_dimensions": len(emb_row),
                    "text": doc[:300],
                })
            result = {
                "chroma_path": s["chroma_path"],
                "collection_name": s["collection_name"],
                "upserted": len(chunks),
                "deleted_stale": len(client_ids_to_delete),
                "collection_total": total,
                "stored_chunks": stored,
            }
            state["collection_total"] = total
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)
        else:
            raise ValueError(f"Unknown ingest step: {key}")

        return {"status": "completed", "step": step, "result": result}

    except Exception as exc:  # surface the error on the node + detail panel
        step["status"] = "error"
        step["error"] = str(exc)
        return {"status": "error", "step": step, "result": {"error": str(exc)}}


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# ────────────────────────── query steps ──────────────────────────

def query_step(run: dict, step_index: int) -> dict:
    """Execute one query-pipeline step; returns {status, data} for the UI node."""
    cfg = run["config"]
    query: str = run["payload"].get("query", "").strip()
    state = run["state"]
    t0 = time.perf_counter()
    step = run["steps"][step_index]
    key = step["key"]

    try:
        if key == "embed_query":
            if not query:
                raise ValueError("Query is empty")
            model = load_embedding_model(cfg["embed_query"]["embed_model"])
            model._client.base_url = cfg["embed_query"]["embed_base_url"]
            vec = model.encode([query])[0].tolist()
            state["query_embedding"] = vec
            result = {
                "query": query,
                "model": model.name,
                "endpoint": str(cfg["embed_query"]["embed_base_url"]),
                "dimensions": len(vec),
                "norm": round(sum(x * x for x in vec) ** 0.5, 4),
                "first_values": [round(x, 6) for x in vec[:8]],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "retrieve":
            collection = load_collection(cfg["store"]["chroma_path"], cfg["store"]["collection_name"])
            model = load_embedding_model(cfg["embed_query"]["embed_model"])
            model._client.base_url = cfg["embed_query"]["embed_base_url"]
            r = cfg["retrieve"]
            top_k = int(r["top_k"])
            if r["retriever"] == "semantic":
                from retrieval import semantic_search as ss
                vec = state.get("query_embedding")
                qe = vec if vec is not None else model.encode([query])[0].tolist()
                raw = collection.query(query_embeddings=[qe], n_results=top_k,
                                       include=["documents", "metadatas", "distances"])
                from retrieval.semantic_search import RetrievedChunk
                final = [RetrievedChunk(content=d, metadata=m, score=dist, rank=i + 1)
                         for i, (d, m, dist) in enumerate(zip(
                             raw["documents"][0], raw["metadatas"][0], raw["distances"][0]))]
                trace = {
                    "vector": [
                        {"doc_id": f"{m.get('doc_title', '?')}_{m.get('chunk_index', '?')}",
                         "doc_title": m.get("doc_title", "?"),
                         "section_title": m.get("section_title", m.get("strategy", "?")),
                         "score": round(dist, 4), "score_key": "distance",
                         "preview": d[:80].replace("\n", " "),
                         "metadata": m}
                        for d, m, dist in zip(raw["documents"][0], raw["metadatas"][0], raw["distances"][0])
                    ],
                    "bm25": [], "fused": [],
                }
            else:
                traced = hybrid_search.search_with_trace(
                    query, collection, model, top_k,
                    rrf_k=int(cfg["rerank"]["rrf_k"]),
                    overfetch_factor=int(r["overfetch_factor"]),
                )
                final = traced["final"]
                trace = traced["trace"]
            state["final_chunks"] = final
            state["trace"] = trace
            result = {
                "retriever": r["retriever"],
                "top_k": top_k,
                "corpus_size": collection.count(),
                "bm25": trace["bm25"],
                "vector": trace["vector"],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "rerank":
            trace = state.get("trace")
            if trace is None:
                raise RuntimeError("No retrieval trace (run 'retrieve' first)")
            result = {"fused": trace["fused"]}
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "augment":
            chunks = state.get("final_chunks") or []
            a = cfg["augment"]
            pm = build_prompt(query, chunks, system_prompt=a.get("system_prompt") or None)
            state["prompt"] = pm
            result = {
                "system": pm.system,
                "user": pm.user,
                "chunks_used": len(chunks),
                "system_prompt_edited": bool(a.get("system_prompt")),
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "generate":
            pm = state.get("prompt")
            if pm is None:
                raise RuntimeError("No prompt built (run 'augment' first)")
            g = cfg["generate"]
            answer = generate(
                pm, query, len(state.get("final_chunks") or []),
                max_tokens=int(g["max_tokens"]),
                temperature=float(g["temperature"]) if g["temperature"] is not None else None,
            )
            result = {
                "text": answer.text,
                "citations": answer.citations,
                "chunks_used": answer.chunks_used,
                "model": g["chat_model"],
                # The chunks the LLM was given, with their stored metadata —
                # this is what the [Source: doc, Section: section] citations
                # resolve to.
                "sources": [
                    {
                        "rank": c.rank,
                        "doc_title": c.metadata.get("doc_title", "?"),
                        "section_title": c.metadata.get("section_title", ""),
                        "chunk_index": c.metadata.get("chunk_index", "?"),
                        "preview": c.content[:160].replace("\n", " "),
                        "metadata": c.metadata,
                    }
                    for c in (state.get("final_chunks") or [])
                ],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)
        else:
            raise ValueError(f"Unknown query step: {key}")

        return {"status": "completed", "step": step, "result": result}

    except Exception as exc:
        step["status"] = "error"
        step["error"] = str(exc)
        return {"status": "error", "step": step, "result": {"error": str(exc)}}


# ────────────────────────── evaluation steps (golden set) ──────────────────────────

def eval_step(run: dict, step_index: int) -> dict:
    """Execute one golden-set generation step; mirrors ingest/query step shape."""
    from eval import golden_generator
    import eval.runner as _eval_runner
    cfg = run["config"]
    state = run["state"]
    t0 = time.perf_counter()
    step = run["steps"][step_index]
    key = step["key"]

    try:
        if key == "load_sections":
            sections = golden_generator._load_sections()
            state["sections"] = sections
            max_sections = int(cfg.get("generate_pairs", {}).get("max_sections", 8))
            state["sections_used"] = sections[:max_sections]
            result = {
                "total_sections": len(sections),
                "used": len(state["sections_used"]),
                "sections": [
                    {"doc_title": s["doc_title"], "section_title": s["section_title"],
                     "chars": len(s["text"])}
                    for s in state["sections_used"]
                ],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "generate_pairs":
            sections: List[dict] = state.get("sections_used")
            if not sections:
                raise RuntimeError("No sections (run 'load_sections' first)")
            g = cfg.get("generate_pairs", {})
            # reuse the generator internals so the section set matches load_sections
            import eval.golden_generator as gg
            t0b = time.perf_counter()
            raw_candidates: List[dict] = []
            client = gg.OpenAI(
                base_url=g.get("gen_chat_base_url", gg.CHAT_BASE_URL),
                api_key=os.getenv("OLLAMA_API_KEY"),
            )
            gen_model = g.get("gen_chat_model", gg.CHAT_MODEL)
            _orig_model = gg.CHAT_MODEL
            gg.CHAT_MODEL = gen_model  # _chat_json/_chat_judge read the module global
            for sec in sections:
                if _eval_runner.is_cancelled(run["id"]):
                    raise _eval_runner.SuiteCancelled("stopped by user")
                raw = gg._chat_json(client, gg.GENERATION_PROMPT.format(
                    doc_title=sec["doc_title"], section_title=sec["section_title"],
                    section_text=sec["text"], n_pairs=int(g.get("pairs_per_section", 2))))
                for item in raw[:int(g.get("pairs_per_section", 2))]:
                    q, a = str(item.get("question", "")).strip(), str(item.get("reference_answer", "")).strip()
                    if not q or not a:
                        continue
                    raw_candidates.append({
                        "id": uuid.uuid4().hex[:8],
                        "kind": "section",
                        "question": q, "reference_answer": a,
                        "doc_title": sec["doc_title"], "section_title": sec["section_title"],
                        "expected_sections": [
                            {"doc_title": sec["doc_title"], "section_title": sec["section_title"]}
                        ],
                    })
            # multi-hop per doc
            by_doc: Dict[str, List[dict]] = {}
            for sec in sections:
                by_doc.setdefault(sec["doc_title"], []).append(sec)
            for doc_title, secs in by_doc.items():
                if len(secs) < 2:
                    continue
                raw = gg._chat_json(client, gg.MULTIHOP_PROMPT.format(
                    section_a=secs[0]["section_title"], section_b=secs[1]["section_title"],
                    section_a_text=secs[0]["text"][:3000], section_b_text=secs[1]["text"][:3000]))
                for item in raw[:1]:
                    q, a = str(item.get("question", "")).strip(), str(item.get("reference_answer", "")).strip()
                    if not q or not a:
                        continue
                    raw_candidates.append({
                        "id": uuid.uuid4().hex[:8],
                        "kind": "multi-hop",
                        "question": q, "reference_answer": a,
                        "doc_title": doc_title,
                        "section_title": f"{secs[0]['section_title']} + {secs[1]['section_title']}",
                        "expected_sections": [
                            {"doc_title": s["doc_title"], "section_title": s["section_title"]} for s in secs[:2]
                        ],
                    })
            # negative cases
            topics = ", ".join(sorted({s["doc_title"] for s in sections}))
            for _ in range(2):
                raw = gg._chat_json(client, gg.NEGATIVE_PROMPT.format(topics=topics))
                for item in raw[:1]:
                    q, a = str(item.get("question", "")).strip(), str(item.get("reference_answer", "")).strip()
                    if not q or not a:
                        continue
                    raw_candidates.append({
                        "id": uuid.uuid4().hex[:8],
                        "kind": "negative",
                        "question": q, "reference_answer": a,
                        "doc_title": "(none)", "section_title": "(fallback expected)",
                        "expected_sections": [],
                    })
            state["raw_candidates"] = raw_candidates
            state["client"] = client
            state["sections"] = sections
            gg.CHAT_MODEL = _orig_model  # restore module default for other callers
            result = {
                "generated": len(raw_candidates),
                "elapsed_ms": int((time.perf_counter() - t0b) * 1000),
                "model": gen_model,
                "endpoint": str(g.get("gen_chat_base_url", gg.CHAT_BASE_URL)),
                "candidates": [
                    {"kind": c["kind"], "doc_title": c["doc_title"],
                     "section_title": c["section_title"],
                     "question": c["question"],
                     "reference_answer": c["reference_answer"][:120] + "…"}
                    for c in raw_candidates
                ],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "filter":
            raw_candidates: List[dict] = state.get("raw_candidates")
            if raw_candidates is None:
                raise RuntimeError("No candidates (run 'generate_pairs' first)")
            f = cfg.get("filter", {})
            if f.get("do_filters", "yes") == "yes":
                import eval.golden_generator as gg
                client = state.get("client") or gg.OpenAI(base_url=gg.CHAT_BASE_URL, api_key=os.getenv("OLLAMA_API_KEY"))
                judge_model = f.get("judge_model", gg.CHAT_MODEL)
                _orig_model = gg.CHAT_MODEL
                gg.CHAT_MODEL = judge_model
                sections = state.get("sections") or []
                kept: List[dict] = []
                closed_book_rejected = grounding_rejected = 0
                for cand in raw_candidates:
                    verdict = gg._chat_judge(client, gg.CLOSED_BOOK_PROMPT.format(question=cand["question"]))
                    if verdict.upper().startswith("ANSWERABLE") and cand["kind"] != "negative":
                        closed_book_rejected += 1
                        cand["rejected"] = f"closed-book answerable ({verdict[:40]})"
                        continue
                    if cand["kind"] in ("section", "multi-hop"):
                        src = next((s["text"][:2500] for s in sections
                                    if s["doc_title"] == cand["doc_title"]
                                    and s["section_title"] in cand.get("section_title", "")),
                                   (sections[0]["text"][:2500] if sections else ""))
                        gverdict = gg._chat_judge(client, gg.GROUNDING_PROMPT.format(
                            source=src, reference_answer=cand["reference_answer"]))
                        if gverdict.upper().startswith("UNSUPP"):
                            grounding_rejected += 1
                            cand["rejected"] = "grounding: reference not supported by source"
                            continue
                    cand.pop("rejected", None)
                    kept.append(cand)
                # dedupe by question embedding similarity
                deduped = 0
                gg.CHAT_MODEL = _orig_model  # restore
                if kept:
                    model = load_embedding_model(f.get("dedupe_model", "nomic-embed-text"))
                    import numpy as np
                    vecs = model.encode([c["question"] for c in kept])
                    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                    unit = vecs / np.maximum(norms, 1e-9)
                    sim = unit @ unit.T
                    thr = float(f.get("dedupe_threshold", 0.9))
                    drop: set = set()
                    for i in range(len(kept)):
                        if i in drop:
                            continue
                        for j in range(i + 1, len(kept)):
                            if sim[i, j] > thr:
                                drop.add(j)
                    deduped = len(drop)
                    kept = [c for i, c in enumerate(kept) if i not in drop]
                state["kept_candidates"] = kept
                state["rejected_candidates"] = [c for c in raw_candidates if c.get("rejected")]
                result = {
                    "generated": len(raw_candidates),
                    "judge_model": judge_model,
                    "closed_book_rejected": closed_book_rejected,
                    "grounding_rejected": grounding_rejected,
                    "deduped": deduped,
                    "kept": len(kept),
                    "rejected": [
                        {"question": c["question"][:90], "reason": c["rejected"]}
                        for c in state["rejected_candidates"]
                    ],
                }
            else:
                state["kept_candidates"] = raw_candidates
                state["rejected_candidates"] = []
                result = {"kept": len(raw_candidates), "filters": "skipped"}
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "review":
            kept: List[dict] = state.get("kept_candidates")
            if not kept:
                raise RuntimeError("No kept candidates (run 'filter' first)")
            existing = golden_generator.load_frozen()
            r = cfg.get("review", {})
            if r.get("freeze_action", "manual") == "all":
                frozen = golden_generator.freeze(kept)
                result = {
                    "awaiting": 0, "frozen": frozen["frozen"], "frozen_path": frozen["path"],
                    "previous_count": len(existing),
                    "candidates": kept,
                }
            else:
                state["pending_freeze"] = kept
                result = {
                    "awaiting": len(kept), "frozen": 0,
                    "previous_count": len(existing),
                    "path": str(golden_generator._golden_path()),
                    "candidates": [
                        {"id": c["id"], "kind": c["kind"], "doc_title": c["doc_title"],
                         "section_title": c["section_title"], "question": c["question"],
                         "reference_answer": c["reference_answer"][:120] + "…"}
                        for c in kept
                    ],
                }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)
        else:
            raise ValueError(f"Unknown eval step: {key}")

        return {"status": "completed", "step": step, "result": result}

    except _eval_runner.SuiteCancelled:
        step["status"] = "cancelled"
        step["error"] = "stopped by user"
        _eval_runner.PROGRESS.pop(run["id"], None)
        _eval_runner.CANCELLED.discard(run["id"])
        return {"status": "cancelled", "step": step,
                "result": {"error": "stopped by user", "cancelled": True}}
    except Exception as exc:
        step["status"] = "error"
        step["error"] = str(exc)
        return {"status": "error", "step": step, "result": {"error": str(exc)}}


# ────────────────────────── misc helpers used by server ──────────────────────────

def list_docs() -> List[dict]:
    """Default documents shown for ingestion (docs/ folder)."""
    docs_dir = PROJECT_ROOT / DOCS_PATH
    out = []
    if docs_dir.exists():
        for f in sorted(docs_dir.iterdir()):
            if f.is_file() and f.suffix == ".md":
                try:
                    text = f.read_text(encoding="utf-8")
                except Exception:
                    text = ""
                out.append({"path": str(Path(DOCS_PATH) / f.name), "title": f.name,
                            "chars": len(text), "words": len(text.split())})
    return out


def browse_files(path: str) -> dict:
    """Server-side folder browser relative to project root."""
    rel = (path or DOCS_PATH).strip()
    base = (PROJECT_ROOT / rel).resolve()
    if PROJECT_ROOT.resolve() not in base.parents and base != PROJECT_ROOT.resolve():
        raise ValueError("Path escapes the project root")
    if not base.exists() or not base.is_dir():
        raise ValueError(f"Not a folder: {rel}")

    dirs, files = [], []
    try:
        for entry in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(Path(rel) / entry.name)})
            else:
                try:
                    text = entry.read_text(encoding="utf-8")
                    words = len(text.split())
                except Exception:
                    words = None  # unreadable/binary — still selectable
                files.append({"name": entry.name, "path": str(Path(rel) / entry.name),
                              "size": entry.stat().st_size, "words": words})
    except PermissionError:
        pass
    return {"path": rel, "parent": str(Path(rel).parent) if Path(rel).parent != Path(".") else None,
            "dirs": dirs, "files": files}


# ────────────────────────── suite steps (Phase 1) ──────────────────────────

def _docs_for_ingest() -> List[str]:
    """docs/*.md relative paths — the corpus the suite re-ingests in ab mode."""
    docs_dir = PROJECT_ROOT / DOCS_PATH
    if not docs_dir.exists():
        raise RuntimeError(f"docs folder not found: {docs_dir}")
    files = sorted(f for f in docs_dir.iterdir() if f.is_file() and f.suffix == ".md")
    if not files:
        raise RuntimeError("docs/ contains no .md files")
    return [str(Path(DOCS_PATH) / f.name) for f in files]


def _reingest(strategy: str, embed_cfg: Dict[str, Any], store_cfg: Dict[str, Any],
              state: Dict[str, Any], log=print) -> int:
    """
    Chunk + embed + store docs/ with the given strategy, mirroring the ingest
    tab's step logic (same splitter params, same stale-delete, same base_url
    override trick). Returns the collection count after upsert.
    """
    from vectorstore.embedder import embed_chunks, load_embedding_model
    from vectorstore.store import get_or_create_collection, load_collection, upsert_chunks

    docs: List[dict] = []
    for rel in _docs_for_ingest():
        path = (PROJECT_ROOT / rel).resolve()
        text = path.read_text(encoding="utf-8")
        docs.append({"path": rel, "title": os.path.basename(rel), "text": text})

    all_chunks: List[Any] = []
    for d in docs:
        if strategy == "structural":
            chunks = split_by_headers(d["text"], d["title"], SEMANTIC_MAX_WORDS)
        elif strategy == "semantic":
            model = load_embedding_model(embed_cfg["embed_model"])
            model._client.base_url = embed_cfg["embed_base_url"]
            chunks = split_by_embeddings(
                d["text"], d["title"], model,
                buffer_size=1, percentile_threshold=95, min_chunk_size=100)
        else:  # character
            chunks = split_by_characters(d["text"], d["title"],
                                         CHAR_CHUNK_SIZE, CHAR_CHUNK_OVERLAP)
        all_chunks.extend(chunks)
    state["chunks"] = all_chunks

    model = load_embedding_model(embed_cfg["embed_model"])
    model._client.base_url = embed_cfg["embed_base_url"]
    embeddings = embed_chunks(all_chunks, model)
    state["embeddings"] = embeddings

    # delete stale chunks of these docs, then upsert (same as ingest 'store')
    stale: List[str] = []
    try:
        existing = load_collection(store_cfg["chroma_path"], store_cfg["collection_name"])
        if existing.count():
            doc_titles = {d["title"] for d in docs}
            got = existing.get(include=["metadatas"])
            stale = [cid for cid, meta in zip(got["ids"], got["metadatas"])
                     if meta.get("doc_title") in doc_titles]
            if stale:
                existing.delete(ids=stale)
    except RuntimeError:
        pass  # collection doesn't exist yet — first ingestion
    collection = get_or_create_collection(store_cfg["chroma_path"], store_cfg["collection_name"])
    upsert_chunks(collection, all_chunks, embeddings)
    log(f"    re-ingested with '{strategy}': {len(all_chunks)} chunks "
        f"({len(stale)} stale deleted), collection now {collection.count()}")
    return collection.count()


def _load_ingest_values() -> Dict[str, Any]:
    """Persisted ingest-side embed/store config (embed model/endpoint, chroma path)."""
    from ui.config_store import load_values
    vals = load_values()
    return {"embed": vals["ingest"]["embed"], "store": vals["ingest"]["store"]}


def suite_step(run: dict, step_index: int) -> dict:
    """Execute one suite (Phase 1) step; mirrors eval_step shape."""
    import eval.runner as eval_runner
    from eval import gate as eval_gate
    from eval.golden_generator import load_frozen
    from vectorstore.embedder import load_embedding_model
    from vectorstore.store import load_collection

    cfg = run["config"]
    state = run["state"]
    t0 = time.perf_counter()
    step = run["steps"][step_index]
    key = step["key"]

    try:
        if key == "load_golden":
            golden = load_frozen()
            if not golden:
                raise RuntimeError("No frozen golden set (eval/golden_set.jsonl). "
                                   "Run the golden-set workflow above first.")
            state["golden"] = golden
            by_kind: Dict[str, int] = {}
            by_section: Dict[str, int] = {}
            for item in golden:
                k = item.get("kind", "section")
                by_kind[k] = by_kind.get(k, 0) + 1
                for s in item.get("expected_sections", []) or []:
                    label = f"{s.get('doc_title', '?')} · {s.get('section_title', '?')}"
                    by_section[label] = by_section.get(label, 0) + 1
            result = {
                "count": len(golden),
                "path": str(eval_runner.EVAL_DIR / "golden_set.jsonl"),
                "by_kind": by_kind,
                "sections_covered": len(by_section),
                "coverage": sorted(by_section.items()),
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "prepare":
            # Resolve the per-leg plan (strategies to run) and inspect the corpus.
            setup = cfg.get("setup", {})
            mode = setup.get("mode", "single")
            state["label"] = (setup.get("label") or "").strip()
            state["ingest_vals"] = _load_ingest_values()
            state["legs"] = ["structural", "character", "semantic"] if mode == "ab" else ["current"]
            state["ab"] = mode == "ab"
            state["leg_index"] = 0
            state["snapshots"] = []
            state["leg_summaries"] = []

            # Warn loudly if the frozen golden set has empty expected_sections:
            # recall would be meaningless (Phase 0 freeze bug guard).
            missing_exp = sum(1 for g in state["golden"]
                              if not g.get("expected_sections") and g.get("kind") != "negative")
            state["missing_expected"] = missing_exp

            store = state["ingest_vals"]["store"]
            collection = load_collection(store["chroma_path"], store["collection_name"])
            result = {
                "mode": mode,
                "strategies": state["legs"] if state["ab"] else None,
                "corpus_size": collection.count(),
                "corpus_strategy": eval_runner._dominant_strategy(collection),
                "missing_expected_sections": missing_exp,
                "warning": (f"{missing_exp} golden items have empty expected_sections — "
                            "recall will read 0. Regenerate + re-freeze the golden set to fix.")
                if missing_exp else None,
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "run_questions":
            if not state.get("golden"):
                raise RuntimeError("No golden set (run 'load_golden' first)")
            retrieve_cfg = cfg.get("retrieve", {})
            gen_cfg = cfg.get("generate", {})
            ingest_vals = state["ingest_vals"]
            legs = state["legs"]
            if state["leg_index"] >= len(legs):
                raise RuntimeError("All legs already executed")
            leg = legs[state["leg_index"]]
            is_ab = state["ab"]

            if is_ab:
                # ab mode: re-ingest docs/ with this leg's strategy first
                _reingest(leg, ingest_vals["embed"], ingest_vals["store"], state, log=lambda m: None)
                strategy_label = leg
            else:
                strategy_label = "current-corpus"

            embedder = load_embedding_model(ingest_vals["embed"]["embed_model"])
            embedder._client.base_url = ingest_vals["embed"]["embed_base_url"]
            store = ingest_vals["store"]
            collection = load_collection(store["chroma_path"], store["collection_name"])

            log_lines: List[str] = []

            # Phase 2 — optional Ragas LLM-judge scoring for this snapshot.
            ragas_cfg = cfg.get("ragas", {}) or {}
            include_ragas = str(ragas_cfg.get("include_ragas", "no")).lower() in ("yes", "true", "1")
            if include_ragas:
                metrics_list = [m.strip() for m in
                                str(ragas_cfg.get("metrics") or "").split(",")
                                if m.strip()]
                r_cfg = {
                    "judge_model": ragas_cfg.get("judge_model"),
                    "judge_base_url": ragas_cfg.get("judge_base_url"),
                    "embed_model": ragas_cfg.get("embed_model"),
                    "embed_base_url": ragas_cfg.get("embed_base_url"),
                    "metrics": metrics_list or None,
                    "max_workers": ragas_cfg.get("max_workers"),
                    "max_wait": ragas_cfg.get("max_wait"),
                }
                log_lines.append(f"ragas enabled: judge={r_cfg['judge_model']} "
                                 f"metrics={metrics_list or '(defaults)'}")
            else:
                r_cfg = None

            snapshot = eval_runner.run_suite(
                state["golden"], collection, embedder,
                chat_cfg=gen_cfg,
                retrieve_cfg=retrieve_cfg,
                strategy=strategy_label,
                log=lambda m: log_lines.append(str(m)),
                include_ragas=include_ragas,
                ragas_cfg=r_cfg,
                run_id=run["id"],
            )
            if state["label"]:
                snapshot["label"] = state["label"]
            path = eval_runner.save_snapshot(snapshot)
            state["snapshots"].append(snapshot)
            state["leg_summaries"].append({
                "leg": leg,
                "strategy": strategy_label,
                "snapshot_id": snapshot["snapshot_id"],
                "aggregate": snapshot["aggregate"],
                "corpus_size": snapshot["config"]["corpus_size"],
                "corpus_strategy": snapshot["config"]["corpus_strategy"],
                "elapsed_ms": snapshot["elapsed_ms"],
                "path": str(path),
            })
            state["leg_index"] += 1
            result = {
                "leg": leg,
                "strategy": strategy_label,
                "leg_index": state["leg_index"],
                "legs_total": len(legs),
                "snapshot_id": snapshot["snapshot_id"],
                "aggregate": snapshot["aggregate"],
                "ragas": snapshot.get("ragas"),
                "corpus_strategy": snapshot["config"]["corpus_strategy"],
                "log_tail": log_lines[-3:],
                "elapsed_ms": snapshot["elapsed_ms"],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        elif key == "compare":
            snapshots: List[dict] = state.get("snapshots") or []
            if not snapshots:
                raise RuntimeError("No snapshots (run 'run_questions' first)")
            baseline = eval_runner.get_baseline()
            # Gate each snapshot of this run against the stored baseline (or
            # the run's own first snapshot when no baseline exists yet).
            ref = baseline if baseline else {
                "snapshot_id": snapshots[0]["snapshot_id"],
                "aggregate": snapshots[0]["aggregate"],
                "results": snapshots[0]["results"],
            }
            diffs = []
            for snap in snapshots:
                d = eval_gate.diff_snapshots(snap, ref)
                d["snapshot_id"] = snap["snapshot_id"]
                d["strategy"] = snap["config"]["strategy"]
                diffs.append(d)
            # cross-leg diff for ab mode: each later leg vs the first leg
            cross = None
            if len(snapshots) > 1:
                cross = [
                    {**eval_gate.diff_snapshots(s, snapshots[0]),
                     "snapshot_id": s["snapshot_id"],
                     "strategy": s["config"]["strategy"]}
                    for s in snapshots[1:]
                ]
            state["diffs"] = diffs
            state["cross"] = cross
            result = {
                "baseline_id": baseline["snapshot_id"] if baseline else None,
                "has_baseline": baseline is not None,
                "diffs": diffs,
                "cross_leg": cross,
                "snapshots": state["leg_summaries"],
            }
            _mark(run, key, status="completed", duration_ms=_ms(t0), result=result)

        else:
            raise ValueError(f"Unknown suite step: {key}")

        return {"status": "completed", "step": step, "result": result}

    except eval_runner.SuiteCancelled:
        step["status"] = "cancelled"
        step["error"] = "stopped by user"
        eval_runner.PROGRESS.pop(run["id"], None)
        eval_runner.CANCELLED.discard(run["id"])
        return {"status": "cancelled", "step": step,
                "result": {"error": "stopped by user", "cancelled": True}}
    except Exception as exc:
        step["status"] = "error"
        step["error"] = str(exc)
        # clear any live progress so the UI stops polling
        from eval import runner as _er
        _er.PROGRESS.pop(run["id"], None)
        return {"status": "error", "step": step, "result": {"error": str(exc)}}