# Enterprise Knowledge Assistant — Hybrid Graph RAG

> Enterprise document RAG combining vector, lexical (BM25) and knowledge-graph retrieval with RRF fusion and an evidence gate before grounded generation.

## What This Project Demonstrates

- Hybrid retrieval across three modes (vector + BM25 + knowledge graph)
- Reciprocal Rank Fusion
- Evidence gating before generation
- Source attribution and grounded answers

## Why This Project Exists

Demonstrates how enterprise knowledge retrieval can combine three complementary signals — vector similarity, keyword matching and knowledge-graph relationships — and gate generation on evidence rather than trusting the LLM alone.

## Architecture

```text
Documents
   ↓
Vector Retrieval + BM25 + Knowledge Graph
   ↓
RRF Fusion
   ↓
Evidence Gate
   ↓
LLM
   ↓
Cited Answer / Refusal
```

## Workflow

*To be verified from code.*

## Technology Stack

| Area | Technology |
|---|---|
| LLM | Ollama |
| Embeddings | nomic-embed-text |
| AI Framework | LlamaIndex, Cognee |
| Vector DB | Qdrant |
| Retrieval | BM25, RRF |
| Knowledge Graph | Graph store (to be verified) |

*To be verified against the project's requirements files.*

## Demo

*Screenshots/demo assets to be added when project code is copied into this repository.*

## How to Run

*To be verified from the project's actual installation and execution instructions.*

## Key AI Engineering Concepts

- Hybrid multi-mode retrieval
- RRF fusion
- Evidence gating & source attribution

## Safety / Reliability

- Evidence gate before answering
- Refusal when evidence is insufficient

## Testing / Evaluation

*To be verified.*

## How This Project Differs

Hybrid vector + lexical + graph retrieval for enterprise knowledge — compared with Production RAG's two-mode hybrid and the Knowledge Graph Builder's graph-native focus.

## AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation decisions, testing, debugging and validation were reviewed and refined during development.