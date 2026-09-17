# Production RAG Documentation Assistant

> A production-oriented RAG system focused on retrieval engineering — chunking, hybrid retrieval, fusion, citations, refusal behavior and regression evaluation — rather than a chat UI.

## What This Project Demonstrates

- Production-oriented RAG retrieval engineering
- Hybrid retrieval (BM25 + vector)
- Grounded generation with citations
- Refusal behavior on unanswerable questions
- Regression evaluation with a frozen golden question set

## Why This Project Exists

Demonstrates retrieval engineering as a discipline — chunking, hybrid retrieval, fusion and refusal behavior — with regression evaluation, rather than simply building another chat UI over a vector store.

## Architecture

*To be verified against source code.*

## Workflow

*To be verified from code.*

## Technology Stack

| Area | Technology |
|---|---|
| LLM | Ollama Cloud |
| Embeddings | nomic-embed-text |
| AI Framework | LangGraph |
| Vector DB | ChromaDB |
| Retrieval | BM25, RRF |
| Backend | FastAPI |
| Evaluation | RAGAS (optional) |

*To be verified against the project's requirements files.*

## Demo

*Screenshots/demo assets to be added when project code is copied into this repository.*

## How to Run

*To be verified from the project's actual installation and execution instructions.*

## Key AI Engineering Concepts

- Hybrid retrieval & RRF fusion
- Citation coverage
- Refusal behavior
- Golden-set regression evaluation (recall@k, must-term coverage)

## Safety / Reliability

- Refusal behavior for unanswerable queries

## Testing / Evaluation

*To be verified — golden question set metrics to be documented from code.*

## How This Project Differs

Retrieval engineering and production-style regression evaluation — distinct from the Enterprise Knowledge Assistant's graph retrieval and the RAG Evaluation Harness (which evaluates RAG systems instead of being one).

## AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation decisions, testing, debugging and validation were reviewed and refined during development.