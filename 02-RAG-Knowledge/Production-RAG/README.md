Languages: **English** | [日本語](README.ja.md)

---

# Production RAG Documentation Assistant

> A production-oriented Retrieval-Augmented Generation pipeline: three chunking strategies, hybrid BM25 + vector retrieval fused with RRF, strictly grounded generation with per-claim citations, honest refusals — and a deterministic regression gate that turns 🟢 the moment quality slips.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-1C3C3C)
![ChromaDB](https://img.shields.io/badge/Vector%20Store-ChromaDB-00C853)
![FastAPI](https://img.shields.io/badge/FastAPI-Visualizer%20UI-009688?logo=fastapi&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud%20gpt--oss%3A120b-white?logo=ollama)
![BM25](https://img.shields.io/badge/Retrieval-BM25%20%2B%20Vectors%20%2B%20RRF-orange)


## Demo Video

[![Production RAG Demo](https://img.youtube.com/vi/nK-iQ_vPdX0/0.jpg)](https://youtu.be/nK-iQ_vPdX0)

## Why This Project Exists

Demonstrates retrieval engineering as a discipline rather than a chat UI: honest hybrid retrieval, answers generated only from retrieved context with per-claim citations, designed refusal behavior — and a frozen golden set + regression gate so quality changes are measured, not felt.

## What This Project Demonstrates

- Three chunking strategies — character (broken baseline), structural with `###` hybrid gate, embedding-semantic — with a comparator that counts broken code blocks/tables
- Hybrid retrieval: BM25 keyword + vector similarity fused by Reciprocal Rank Fusion (`k=60`)
- Strictly grounded generation with `[Source: doc, Section: …]` citations or explicit refusal
- Two-phase evaluation: deterministic LLM-free metrics + optional Ragas LLM judge
- A regression gate (🟢/🟡/🔴 vs baseline) with 30 recorded snapshot history

## Architecture

```text
INGESTION (offline)
docs/*.md → Chunk (3 strategies) → Embed (nomic-embed-text) → ChromaDB

QUERY TIME (online)
Question → Hybrid search (BM25 + vector + RRF) → Grounded prompt
         → Generate (gpt-oss:120b) → Cited answer | Refusal

EVALUATION
19-question frozen golden set → live pipeline → snapshot JSON
→ gate diff vs baseline → 🟢 PASS / 🟡 WARN / 🔴 FAIL (exit code for CI)
```

A three-node LangGraph `StateGraph` (`retrieve → build_prompt → generate`) composes the query path, with a conditional edge that short-circuits to END on retrieval error — nodes never throw, they set a readable error string.

## Workflow

1. **Ingest** — load Markdown, chunk with the chosen strategy, embed, upsert into a persistent ChromaDB collection (stale chunks deleted per-document before re-ingest)
2. **Ask** — embed the query, run BM25 and vector search in parallel (2× overfetch), fuse rankings with RRF, inject top-5 chunks with source labels, generate a cited answer
3. **Refuse** — questions outside the corpus get *"I could not find an answer to this question in the provided documentation."* — a designed, measured behavior (dedicated negative questions in the suite)
4. **Gate** — replay the 19-question golden set through the live pipeline, snapshot the metrics, diff against baseline; any quality metric dropping >0.05 is 🟡, >0.15 is 🔴 (CI non-zero exit)

## Technology Stack

| Area | Technology |
|---|---|
| LLM | Ollama Cloud (`gpt-oss:120b`) — chat/answer generation |
| Embeddings | `nomic-embed-text` (768-d) via local Ollama |
| AI Framework | LangGraph (`StateGraph`, 3 pure-function nodes) |
| Vector DB | ChromaDB (persistent, HNSW) |
| Retrieval | BM25 (`rank_bm25`), cosine vectors, RRF fusion |
| Backend | FastAPI step-by-step visualizer (vanilla JS SPA) |
| Evaluation | Deterministic metrics + optional Ragas LLM judge (`glm-5.3-flash`) |

## Key AI Engineering Concepts

- **Chunks are the atoms of retrieval** — the demo proves the same query returns fragments under character splitting and a clean cited answer under structural splitting
- **Two retrievers beat one** — vectors find meaning, BM25 finds exact tokens (`MCPToolset`, `X-Goog-Api-Key`); RRF merges by rank, no score calibration needed
- **Grounded generation** — the system prompt forbids inference; every claim must cite a retrieved chunk
- **Golden sets from your corpus** — LLM-generated then hardened by closed-book, grounding and dedupe (0.9 cosine) filters before freezing

## Safety / Reliability

- Refusal behavior is designed and **measured** (`refusal_accuracy` on 2 dedicated negative questions)
- Regression gate watches recall, citation coverage, must-term coverage, refusal accuracy and latency — Ragas LLM scores ride along but never flip the verdict (deterministic, reproducible gate)
- Nodes capture errors as state instead of raising; failed retrieval ends the graph with one readable message
- Temperature pinned to 0 for suite reproducibility; snapshot records the full config (strategy, retriever, top_k, models, corpus)

## Testing / Evaluation

Verified metrics from the shipped baseline (`eval/BASELINE.json`, 46 embedding-semantic chunks, hybrid retrieval, top-5):

| Metric | Value |
|---|---|
| recall@k | **1.0** (every answerable question hit its section) |
| first relevant rank | 1.18 |
| must-term coverage | 0.67 |
| refusal accuracy | 0.5 |
| latency | mean 2.2s / p95 3.2s per question |

- **19-question frozen golden set** (15 section · 2 multi-hop · 2 negative), LLM-generated from the corpus and hardened by closed-book + grounding + dedupe filters
- **30 evaluation snapshots** recorded; gate diffs each run vs baseline (or any two snapshots)
- Golden-set generation is reproducible: 2 pairs per section + multi-hop + negative cases, all filter-verified before freezing

## Demo

Full walkthrough: [`RAG_Production_Userguide.html`](RAG_Production_Userguide.html) — 4-tab guide (Elevator Pitch / Non-Technical / Technical / Glossary) with pipeline, module map and gate-flow diagrams. Project documentation: [`Project_Documentation.md`](Project_Documentation.md).

The FastAPI visualizer serves three tabs — **Ingestion**, **Inference**, **Evaluation** — where every pipeline step runs one at a time with detail panels (chunk previews, BM25/vector/fused ranking traces, stored ChromaDB rows, gate diff tables).

## How to Run

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure .env (project root — see settings in config/settings.py)
#    OLLAMA_API_KEY=<your ollama.com key>
#    OLLAMA_CHAT_BASE_URL=https://ollama.com/v1
#    OLLAMA_CHAT_MODEL=gpt-oss:120b
#    OLLAMA_EMBED_BASE_URL=http://localhost:11434/v1
#    OLLAMA_EMBED_MODEL=nomic-embed-text

# 3. Keep local Ollama running (serves the embeddings model)

# 4. Start the visualizer
python -m uvicorn ui.server:app --port 8000
#    → open http://localhost:8000

# Optional CLI chunking demo
python demo/01_chunking_comparison.py

# Evaluation gate from CLI
python -m eval.gate <snapshot_id>
```

Requires an Ollama Cloud API key for chat and a local Ollama with `nomic-embed-text` for embeddings.

## Project Structure

```text
Production-RAG/
├── chunking/          # character · structural (H2+H3 gate) · embedding-semantic · comparison
├── vectorstore/       # embedder (OpenAI-compatible) · ChromaDB store (upsert, stale delete)
├── retrieval/         # pure vector search · hybrid BM25+vector+RRF with per-stage trace
├── generation/        # grounded prompt builder · answer generator with citation regex
├── pipeline/          # LangGraph StateGraph: state · nodes (try/except) · graph (conditional edge)
├── eval/              # golden_generator (LLM + 3 filters) · metrics · runner · gate · ragas_eval
│   └── snapshots/     # 30 recorded runs + BASELINE.json + golden_set.jsonl (19 pairs)
├── ui/                # FastAPI visualizer: step-by-step runners, param config, static SPA
├── docs/              # 2 source Markdown documents (healthcare MCP guide, AI-agents-vs-MCP)
├── demo/              # CLI demo sequence proving the chunking story
├── main.py            # demo sequence entry point
└── RAG_Production_Userguide.html
```

## How This Project Differs

Retrieval engineering plus production-style regression evaluation — distinct from the Enterprise Knowledge Assistant (which adds graph retrieval and an evidence gate) and the RAG Evaluation Harness (which evaluates any RAG endpoint instead of being one).

## AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation decisions, testing, debugging and validation were reviewed and refined during development.