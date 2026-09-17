"""
UI configuration store.

- PARAM_META declaratively describes every configurable parameter exposed in
  the UI: id, label, type, default, options, hover-help text and visibility
  rules (e.g. character chunk params only shown for the character strategy).
- Values are persisted to ui_config.json so user changes survive restarts.
- config/settings.py defaults are never mutated; values are applied per-run
  as function arguments.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import (
    CHROMA_PATH,
    COLLECTION_NAME,
    CHAT_BASE_URL,
    CHAT_MODEL,
    EMBED_BASE_URL,
    EMBED_MODEL,
    SEMANTIC_MAX_WORDS,
    CHAR_CHUNK_OVERLAP,
    CHAR_CHUNK_SIZE,
    TOP_K,
)

UI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = UI_DIR.parent
CONFIG_FILE = UI_DIR / "ui_config.json"

# Keep in sync with generation/prompt_builder.build_prompt's default so the
# UI's untouched default behaves identically to the CLI pipeline.
DEFAULT_SYSTEM_PROMPT = (
    "You are a documentation assistant. "
    "Answer ONLY using the information in the provided document chunks.\n\n"
    "If the answer is not present in the chunks, respond with:\n"
    "'I could not find an answer to this question in the provided documentation.'\n\n"
    "Do not infer, guess, or use external knowledge.\n\n"
    "For every claim in your answer, cite the source using this format:\n"
    "[Source: <doc_title>, Section: <section_title>]"
)

# Workflow node definitions per tab (order defines the graph top-to-bottom).
STEP_DEFS = {
    "ingest": [
        {"key": "load", "title": "Load Documents", "icon": "📄"},
        {"key": "chunk", "title": "Chunk", "icon": "✂️"},
        {"key": "embed", "title": "Embed", "icon": "🧮"},
        {"key": "store", "title": "Store (Upsert)", "icon": "💾"},
    ],
    "query": [
        {"key": "embed_query", "title": "Embed Query", "icon": "🧭"},
        {"key": "retrieve", "title": "Retrieve (Candidates)", "icon": "🔍"},
        {"key": "rerank", "title": "Rerank (RRF)", "icon": "📊"},
        {"key": "augment", "title": "Augment (Prompt)", "icon": "🧩"},
        {"key": "generate", "title": "Generate", "icon": "💬"},
    ],
    "eval": [
        {"key": "load_sections", "title": "Load Sections", "icon": "📚"},
        {"key": "generate_pairs", "title": "Generate Q/A Pairs", "icon": "🤖"},
        {"key": "filter", "title": "Auto-Filters", "icon": "🧪"},
        {"key": "review", "title": "Review & Freeze", "icon": "✔️"},
    ],
    # Pseudo-workflow: rendered inside the Evaluation tab, below the golden-set
    # workflow. Runs the frozen golden set through the live pipeline and writes
    # regression snapshots (Phase 1).
    "suite": [
        {"key": "load_golden", "title": "Load Golden Set", "icon": "📋"},
        {"key": "prepare", "title": "Prepare Corpus", "icon": "🧰"},
        {"key": "run_questions", "title": "Run Questions", "icon": "🏃"},
        {"key": "compare", "title": "Compare & Gate", "icon": "⚖️"},
    ],
}

Param = Dict[str, Any]

PARAM_META: Dict[str, Dict[str, List[Param]]] = {
    "ingest": {
        "load": [
            {"id": "file_pattern", "label": "File pattern", "type": "text", "default": ".md",
             "help": "Only files whose name ends with this pattern are loaded. Default '.md' matches the Markdown docs in docs/."},
            {"id": "encoding", "label": "Encoding", "type": "text", "default": "utf-8",
             "help": "Text encoding used to read the files. 'utf-8' is standard for Markdown sources."},
        ],
        "chunk": [
            {"id": "strategy", "label": "Chunking strategy", "type": "select", "default": "structural",
             "options": ["structural", "character", "semantic"],
             "help": "structural: splits at ## header boundaries so sections stay intact (oversized sections are further split at ### headers). character: fixed-size windows that may cut code blocks and tables mid-way. semantic: embedding-based — splits into sentences and cuts where consecutive-sentence similarity drops (topic shift), no LLM involved."},
            {"id": "char_chunk_size", "label": "Chunk size (chars)", "type": "int", "default": CHAR_CHUNK_SIZE,
             "visible_if": {"step": "chunk", "param": "strategy", "equals": "character"},
             "help": "Number of characters per chunk when using the character strategy. Smaller values produce more, smaller chunks."},
            {"id": "char_chunk_overlap", "label": "Overlap (chars)", "type": "int", "default": CHAR_CHUNK_OVERLAP,
             "visible_if": {"step": "chunk", "param": "strategy", "equals": "character"},
             "help": "Characters repeated between consecutive character-strategy chunks. Overlap preserves continuity but duplicates text."},
            {"id": "semantic_max_words", "label": "Max words per section", "type": "int", "default": SEMANTIC_MAX_WORDS,
             "visible_if": {"step": "chunk", "param": "strategy", "equals": "structural"},
             "help": "With the structural strategy, H2 sections longer than this many words are further split at ### header boundaries. Higher = fewer, larger chunks."},
            {"id": "sem_buffer_size", "label": "Similarity buffer", "type": "int", "default": 1,
             "visible_if": {"step": "chunk", "param": "strategy", "equals": "semantic"},
             "help": "How many consecutive similar-boundary candidates to merge into one breakpoint (Greg Kamradt buffer). Higher = fewer, larger chunks."},
            {"id": "sem_percentile", "label": "Similarity percentile", "type": "int", "default": 95,
             "visible_if": {"step": "chunk", "param": "strategy", "equals": "semantic"},
             "help": "A breakpoint is cut where consecutive-sentence cosine similarity falls below this percentile of all pair similarities. Higher percentile = fewer breakpoints = larger chunks."},
            {"id": "sem_min_chunk_size", "label": "Min chunk size (chars)", "type": "int", "default": 100,
             "visible_if": {"step": "chunk", "param": "strategy", "equals": "semantic"},
             "help": "Chunks shorter than this many characters are merged into the previous chunk to avoid fragmented topics."},
        ],
        "embed": [
            {"id": "embed_model", "label": "Embedding model", "type": "text", "default": EMBED_MODEL,
             "help": "Name of the embedding model served at the embeddings endpoint (e.g. local Ollama 'nomic-embed-text'). Must match the model used at query time."},
            {"id": "embed_base_url", "label": "Embedding endpoint", "type": "text", "default": EMBED_BASE_URL,
             "help": "OpenAI-compatible /v1 endpoint that serves the embedding model. Local Ollama default: http://localhost:11434/v1"},
        ],
        "store": [
            {"id": "chroma_path", "label": "Chroma path", "type": "text", "default": CHROMA_PATH,
             "help": "Folder (relative to the project root) where ChromaDB persists its data on disk."},
            {"id": "collection_name", "label": "Collection name", "type": "text", "default": COLLECTION_NAME,
             "help": "ChromaDB collection name. Ingestion upserts: a re-ingested doc_title + chunk_index replaces the old chunk; stale chunks of the selected docs are deleted first."},
        ],
    },
    "query": {
        "embed_query": [
            {"id": "embed_model", "label": "Embedding model", "type": "text", "default": EMBED_MODEL,
             "help": "Embedding model used to vectorize the question. Must be the same model the documents were ingested with, otherwise the vector spaces do not align."},
            {"id": "embed_base_url", "label": "Embedding endpoint", "type": "text", "default": EMBED_BASE_URL,
             "help": "OpenAI-compatible /v1 endpoint for embeddings. Local Ollama default: http://localhost:11434/v1"},
        ],
        "retrieve": [
            {"id": "retriever", "label": "Retriever", "type": "select", "default": "hybrid",
             "options": ["hybrid", "semantic"],
             "help": "hybrid: BM25 keyword ranking + vector similarity, fused in the next step (RRF). semantic: pure vector similarity only (distance-based ranking)."},
            {"id": "top_k", "label": "Top K (final)", "type": "int", "default": TOP_K,
             "help": "Number of chunks finally kept after reranking and sent to the LLM."},
            {"id": "overfetch_factor", "label": "Vector overfetch ×", "type": "int", "default": 2,
             "visible_if": {"step": "retrieve", "param": "retriever", "equals": "hybrid"},
             "help": "Vector search fetches top_k × this many candidates before fusion, giving the RRF reranker more material. Higher = broader recall, slightly slower."},
        ],
        "rerank": [
            {"id": "rrf_k", "label": "RRF constant k", "type": "int", "default": 60,
             "visible_if": {"step": "retrieve", "param": "retriever", "equals": "hybrid"},
             "help": "Reciprocal Rank Fusion smoothing constant: score = 1/(rank + k) per ranked list. 60 is the classic default; larger k dampens the advantage of rank-1 results."},
        ],
        "augment": [
            {"id": "system_prompt", "label": "System prompt", "type": "textarea", "default": DEFAULT_SYSTEM_PROMPT,
             "help": "System instruction sent to the LLM. The default enforces strict grounding (answer only from chunks) and the [Source: <doc_title>, Section: <section_title>] citation format."},
        ],
        "generate": [
            {"id": "chat_model", "label": "Chat model", "type": "text", "default": CHAT_MODEL,
             "help": "Chat model name served at the chat endpoint, e.g. 'gpt-oss:120b' on Ollama Cloud."},
            {"id": "chat_base_url", "label": "Chat endpoint", "type": "text", "default": CHAT_BASE_URL,
             "help": "OpenAI-compatible /v1 endpoint for the chat model (Ollama Cloud by default)."},
            {"id": "max_tokens", "label": "Max tokens", "type": "int", "default": 2048,
             "help": "Maximum tokens in the response. gpt-oss is a reasoning model: thinking tokens count toward this budget, so too low a value can truncate the visible answer."},
            {"id": "temperature", "label": "Temperature", "type": "float", "default": 1.0,
             "help": "Sampling temperature: 0 = deterministic, higher = more creative. 1.0 matches the previous pipeline behavior (provider default)."},
        ],
    },
    "eval": {
        "generate_pairs": [
            {"id": "gen_chat_model", "label": "Generator LLM", "type": "text", "default": CHAT_MODEL,
             "help": "Chat model that writes the question/reference-answer pairs (e.g. gpt-oss:120b on Ollama Cloud). Must be a model served at the generator endpoint."},
            {"id": "gen_chat_base_url", "label": "Generator endpoint", "type": "text", "default": CHAT_BASE_URL,
             "help": "OpenAI-compatible /v1 endpoint for the generator LLM (Ollama Cloud by default). Embeddings for dedupe always use the local Ollama embedder."},
            {"id": "pairs_per_section", "label": "Pairs per section", "type": "int", "default": 2,
             "help": "How many question/answer pairs the LLM writes for each documentation section. Higher = more coverage, more LLM calls."},
            {"id": "max_sections", "label": "Max sections", "type": "int", "default": 8,
             "help": "Cap on how many documentation sections are processed. Lower = faster generation runs."},
        ],
        "filter": [
            {"id": "judge_model", "label": "Judge LLM", "type": "text", "default": CHAT_MODEL,
             "help": "Model used for the closed-book and grounding judge passes (small/fast model is fine — verdicts are one word)."},
            {"id": "do_filters", "label": "Run auto-filters", "type": "select", "default": "yes",
             "options": ["yes", "no"],
             "help": "yes: reject questions the LLM can answer without the docs (closed-book check), verify reference answers are grounded in the source, and dedupe near-identical questions by embedding similarity."},
            {"id": "dedupe_threshold", "label": "Dedupe similarity", "type": "float", "default": 0.9,
             "visible_if": {"step": "filter", "param": "do_filters", "equals": "yes"},
             "help": "Questions with cosine similarity above this value are considered duplicates; only the first is kept."},
            {"id": "dedupe_model", "label": "Dedupe embedder", "type": "text", "default": EMBED_MODEL,
             "help": "Local embedding model used to embed questions for dedupe (nomic-embed-text via local Ollama)."},
        ],
        "review": [
            {"id": "freeze_action", "label": "Freeze action", "type": "select", "default": "manual",
             "options": ["manual", "all"],
             "help": "manual: freeze only the items you checked in the review list (default). all: freeze every kept candidate automatically when the run completes."},
        ],
    },
    "suite": {
        "setup": [
            {"id": "mode", "label": "Run mode", "type": "select", "default": "single",
             "options": ["single", "ab"],
             "help": "single: score the golden set against the corpus currently in ChromaDB (no re-ingestion). ab: one run scores all three chunking strategies — docs are re-chunked, re-embedded and re-stored per strategy before its leg runs. After an ab run the collection holds the LAST leg's chunks."},
            {"id": "label", "label": "Run label", "type": "text", "default": "",
             "help": "Optional free-text label stored in the snapshot (e.g. 'after prompt tweak') so runs are tellable apart in the snapshot list."},
        ],
        "retrieve": [
            {"id": "retriever", "label": "Retriever", "type": "select", "default": "hybrid",
             "options": ["hybrid", "semantic"],
             "help": "hybrid: BM25 + vector similarity fused by RRF. semantic: pure vector similarity only. Switch between them to A/B retrieval quality on the same corpus."},
            {"id": "top_k", "label": "Top K (final)", "type": "int", "default": TOP_K,
             "help": "Number of chunks kept per question after ranking."},
            {"id": "overfetch_factor", "label": "Vector overfetch ×", "type": "int", "default": 2,
             "visible_if": {"step": "retrieve", "param": "retriever", "equals": "hybrid"},
             "help": "Vector search fetches top_k × this many candidates before RRF fusion."},
            {"id": "rrf_k", "label": "RRF constant k", "type": "int", "default": 60,
             "visible_if": {"step": "retrieve", "param": "retriever", "equals": "hybrid"},
             "help": "Reciprocal Rank Fusion smoothing constant (same meaning as in the Inference tab)."},
        ],
        "generate": [
            {"id": "chat_model", "label": "Chat model", "type": "text", "default": CHAT_MODEL,
             "help": "Chat model that answers the golden questions during the suite run (gpt-oss:120b on Ollama Cloud by default)."},
            {"id": "chat_base_url", "label": "Chat endpoint", "type": "text", "default": CHAT_BASE_URL,
             "help": "OpenAI-compatible /v1 endpoint for the chat model (Ollama Cloud by default)."},
            {"id": "max_tokens", "label": "Max tokens", "type": "int", "default": 2048,
             "help": "Max tokens per answer. gpt-oss is a reasoning model: thinking tokens count toward this budget."},
            {"id": "temperature", "label": "Temperature", "type": "float", "default": 0.0,
             "help": "0 makes suite runs reproducible (recommended for evaluation); higher values trade determinism for creativity."},
        ],
        # Phase 2 — Ragas LLM-judged scoring (optional, off by default so the
        # cheap deterministic gate stays LLM-free).
        "ragas": [
            {"id": "include_ragas", "label": "Run Ragas scoring", "type": "select", "default": "no",
             "options": ["no", "yes"],
             "help": "Off: suite finishes fast with deterministic metrics only. On: after generation, every answer is additionally judged by Ragas (faithfulness / context precision / context recall) using the judge LLM — adds roughly one judge call per metric per question, so expect minutes instead of seconds."},
            {"id": "judge_model", "label": "Judge LLM", "type": "text", "default": "glm-5.3-flash",
             "visible_if": {"step": "ragas", "param": "include_ragas", "equals": "yes"},
             "help": "Model the Ragas judge runs on. Default glm-5.3-flash: non-reasoning, ~3 s per call, robust to Ollama Cloud congestion. Avoid slow reasoning models (gpt-oss) here — under load their calls stretch to minutes and the judge pass can take hours."},
            {"id": "judge_base_url", "label": "Judge endpoint", "type": "text", "default": "https://ollama.com/v1",
             "visible_if": {"step": "ragas", "param": "include_ragas", "equals": "yes"},
             "help": "OpenAI-compatible base URL for the judge. langchain's ChatOpenAI uses it verbatim (no /v1 is appended), so include /v1 — https://ollama.com/v1 for Ollama Cloud."},
            {"id": "embed_model", "label": "Ragas embedder", "type": "text", "default": "nomic-embed-text",
             "visible_if": {"step": "ragas", "param": "include_ragas", "equals": "yes"},
             "help": "Embedding model used by Ragas' answer-relevancy metric. Must be served at the Ragas embedding endpoint (local Ollama nomic-embed-text)."},
            {"id": "embed_base_url", "label": "Ragas embedding endpoint", "type": "text", "default": "http://localhost:11434/v1",
             "visible_if": {"step": "ragas", "param": "include_ragas", "equals": "yes"},
             "help": "OpenAI-compatible base URL for Ragas' embedder (used verbatim — include /v1: http://localhost:11434/v1 for local Ollama)."},
            {"id": "metrics", "label": "Metrics", "type": "text", "default": "faithfulness,context_precision,context_recall",
             "visible_if": {"step": "ragas", "param": "include_ragas", "equals": "yes"},
             "help": "Comma-separated Ragas metrics to run. Available: faithfulness, context_precision, context_recall, answer_relevancy (answer_relevancy also needs the embedder). Fewer metrics = faster runs."},
            {"id": "max_workers", "label": "Parallel questions", "type": "int", "default": 2,
             "visible_if": {"step": "ragas", "param": "include_ragas", "equals": "yes"},
             "help": "How many questions Ragas judges concurrently. Keep low — Ollama Cloud rate-limits; 2 is the safe default."},
            {"id": "max_wait", "label": "Judge timeout (s)", "type": "int", "default": 180,
             "visible_if": {"step": "ragas", "param": "include_ragas", "equals": "yes"},
             "help": "Per-call timeout in seconds (each judge LLM call gets this budget; a metric makes 2+ calls per question). gpt-oss reasoning calls take 50-90 s, so keep this ≥ 180. For faster judging use judge_model glm-5.2 (a few seconds per call)."},
        ],
    },
}


def default_values() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Fresh nested dict of every default value from PARAM_META."""
    return {
        tab: {
            step: {p["id"]: deepcopy(p["default"]) for p in params}
            for step, params in steps.items()
        }
        for tab, steps in PARAM_META.items()
    }


def _merge(target: Dict[str, Any], saved: Dict[str, Any]) -> None:
    """Copy known param ids from `saved` into `target` (unknown ids ignored)."""
    for tab, steps in saved.items():
        if tab not in target or not isinstance(steps, dict):
            continue
        for step, params in steps.items():
            if step not in target[tab] or not isinstance(params, dict):
                continue
            for pid, value in params.items():
                if pid in target[tab][step]:
                    target[tab][step][pid] = value


def load_values() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Defaults merged with whatever the user persisted in ui_config.json."""
    values = default_values()
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                _merge(values, saved)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt/ unreadable file -> fall back to defaults
    return values


def save_values(saved: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Merge user values over defaults, persist, and return the merged dict."""
    values = default_values()
    if isinstance(saved, dict):
        _merge(values, saved)
    CONFIG_FILE.write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")
    return values


def reset_values() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Delete ui_config.json and return fresh defaults."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    return default_values()