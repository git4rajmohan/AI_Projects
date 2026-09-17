# Plan — Production-Grade RAG Project

## 1. Project Goal

Build a domain-specific, production-quality Retrieval-Augmented Generation (RAG) application that can:

- Ingest PDF, Markdown, and web documents.
- Split documents into useful chunks.
- Generate embeddings and store them in a vector database.
- Retrieve relevant evidence for a user question.
- Generate grounded answers using an LLM.
- Show exact source citations/paragraphs.
- Refuse to answer when the retrieved evidence is insufficient.
- Use hybrid retrieval combining semantic vector search and BM25.
- Improve retrieval with a cross-encoder re-ranker.
- Version prompts as configuration.
- Evaluate the system using a manually verified golden dataset.
- Run RAG quality checks in CI and fail the build when quality drops below defined thresholds.

The project should clearly demonstrate the difference between a basic RAG demo and an engineered, shippable RAG system.

---

# 2. Recommended Demo Domain

Use **technical documentation** as the initial corpus because it is easy to demonstrate:

- precise questions,
- exact source paragraphs,
- citations,
- terminology-heavy searches,
- keyword vs semantic retrieval,
- unsupported questions,
- evaluation datasets.

The architecture should remain domain-agnostic so the corpus can later be replaced with legal, research, business, or other documents.

---

# 3. Three-Phase Implementation

## Phase 1 — RAG Fundamentals

### Objective

Build the minimum complete RAG pipeline and prove that answers are grounded in source documents.

### Step 1 — Project Setup

Create a clean project structure similar to:

```text
rag-project/
├── app/
│   ├── ingestion/
│   ├── chunking/
│   ├── embeddings/
│   ├── retrieval/
│   ├── generation/
│   ├── citations/
│   └── config/
├── data/
│   ├── documents/
│   └── processed/
├── evaluation/
├── tests/
├── scripts/
├── prompts/
├── config/
├── requirements.txt
├── .env.example
├── README.md
└── plan.md
```

Keep components modular so individual retrieval or model components can be replaced later.

### Step 2 — Document Ingestion

Support:

- PDF
- Markdown
- Web pages

For every document, preserve metadata such as:

- document name
- source URL, when applicable
- page number, when applicable
- section/heading
- chunk ID

This metadata will later be used for citations.

### Step 3 — Chunking

Start with:

- approximately 500–800 tokens per chunk
- approximately 100 tokens overlap

Make chunk size and overlap configurable.

The goal is to prevent important context from being lost at chunk boundaries.

### Step 4 — Embeddings

Create embeddings for every chunk.

Prefer a local/open-source embedding model where practical.

Make the embedding model configurable.

Important:

- Store the embedding model name/version in configuration.
- Keep embedding generation separate from retrieval.
- Detect vector-dimension mismatches clearly.

### Step 5 — Vector Store

Start with **ChromaDB** because it is easy to run locally.

Keep the vector-store interface abstract enough to support another backend later.

### Step 6 — Basic Retrieval

Implement:

```text
User Question
     ↓
Query Embedding
     ↓
Vector Search
     ↓
Top-K Chunks
     ↓
LLM
     ↓
Answer + Citations
```

Make Top-K configurable.

### Step 7 — Citation Display

Every answer should identify the supporting evidence.

Example:

```text
Answer:
The system supports X because ...

Sources:
[1] document.pdf — Page 12
    "Exact supporting paragraph..."

[2] documentation.md — Section: Authentication
    "Exact supporting paragraph..."
```

The user should be able to trace an answer back to the original document.

### Phase 1 Acceptance Criteria

Phase 1 is complete when:

- Documents can be ingested.
- Documents are chunked.
- Embeddings are generated.
- ChromaDB stores the chunks.
- Questions retrieve relevant chunks.
- The LLM generates an answer.
- Citations identify the supporting source.
- The application can demonstrate the complete workflow locally.

---

# 4. Phase 2 — Production-Quality RAG

## Objective

Upgrade the basic RAG pipeline into a higher-precision retrieval and answer-generation system.

## Step 8 — Hybrid Retrieval

Implement two retrieval strategies:

### Semantic Retrieval

Use vector similarity to capture:

- meaning
- intent
- semantic similarity

### Keyword Retrieval

Implement **BM25** for exact terminology and keyword matching.

The combined flow should be:

```text
                    ┌── Vector Search ──┐
User Query ─────────┤                   ├──> Combined Candidates
                    └── BM25 Search ────┘
```

Make the weighting/configuration adjustable.

## Step 9 — Candidate Fusion

Retrieve candidates from both BM25 and vector search.

Combine and deduplicate the candidates before re-ranking.

Track retrieval metadata so evaluation can determine which method contributed each result.

## Step 10 — Cross-Encoder Re-Ranking

Add a cross-encoder re-ranker.

The re-ranker should evaluate:

```text
Query + Chunk
```

as a pair and produce a relevance score.

Recommended open-source direction:

- Sentence Transformers cross-encoder models.

Keep Cohere Reranker as an optional cloud implementation rather than a mandatory dependency.

Pipeline:

```text
Query
  ↓
BM25 + Vector Retrieval
  ↓
Candidate Pool
  ↓
Cross-Encoder Re-Ranker
  ↓
Top Relevant Chunks
  ↓
LLM
```

## Step 11 — Citation Enforcement

The application must not treat every retrieved chunk as sufficient evidence.

Implement an evidence-support check.

If evidence is insufficient:

```text
Insufficient Evidence
        ↓
Decline to Answer
```

Example behavior:

```text
I don't have enough evidence in the provided documents
to answer this question reliably.
```

Do not allow the LLM to invent an answer merely because the question sounds plausible.

## Step 12 — Prompt Versioning

Store prompts separately from application code.

Example:

```text
prompts/
├── system_v1.txt
├── rag_answer_v1.txt
├── citation_v1.txt
└── refusal_v1.txt
```

Or use a YAML/JSON configuration containing prompt versions.

The active prompt version should be visible in configuration and logs.

Treat prompts as part of the system architecture.

## Step 13 — Observability

Log enough information to debug a RAG response:

- request ID
- query
- retrieval strategy
- retrieved chunk IDs
- retrieval scores
- reranker scores
- prompt version
- model name
- latency
- final answer
- citation IDs
- refusal reason, when applicable

Do not log secrets.

### Phase 2 Acceptance Criteria

Phase 2 is complete when:

- BM25 retrieval works.
- Vector retrieval works.
- Hybrid retrieval works.
- Candidates are re-ranked.
- Citations are evidence-backed.
- Unsupported questions trigger refusal.
- Prompts are versioned.
- Important pipeline information is observable through logs.

---

# 5. Phase 3 — Truly Shippable RAG

## Objective

Continuously measure RAG quality and enforce quality through automated evaluation and CI.

## Step 14 — Golden Evaluation Dataset

Create approximately **50–200 manually verified question-answer pairs**.

Each test case should contain fields similar to:

```text
id
question
expected_answer
expected_source
expected_source_section
difficulty
category
```

Include different categories:

- straightforward factual questions
- multi-hop questions
- terminology-heavy questions
- semantic paraphrases
- questions with distractor documents
- unsupported questions
- intentionally ambiguous questions

The dataset becomes the baseline for regression testing.

## Step 15 — Offline Evaluation

Create an evaluation script that runs the complete RAG pipeline against the golden dataset.

Measure at minimum:

### Faithfulness

Are the claims in the generated answer supported by retrieved evidence?

Also consider measuring:

- answer correctness
- context relevance
- context recall
- citation correctness
- retrieval precision
- refusal accuracy
- latency

Use **Ragas** where appropriate, while keeping custom checks for citation and refusal behavior.

Example:

```text
Golden Dataset
      ↓
Run RAG
      ↓
Collect Answers + Retrieved Evidence
      ↓
Evaluate
      ↓
Metrics
      ↓
Pass / Fail
```

## Step 16 — Evaluation Report

Generate a machine-readable result such as:

```text
evaluation/results.json
evaluation/results.csv
```

Include:

- overall scores
- per-question scores
- failed questions
- retrieved sources
- generated answer
- expected answer
- failure reason

Make failures easy to inspect.

## Step 17 — Define Quality Gates

Example configurable thresholds:

```yaml
quality_gates:
  faithfulness: 0.85
  answer_correctness: 0.80
  context_relevance: 0.80
  citation_accuracy: 0.90
```

These are starting values, not universal requirements. Adjust them after establishing a baseline.

## Step 18 — CI Integration

Run the evaluation automatically in CI.

Example:

```text
Code Change
    ↓
CI Build
    ↓
Tests
    ↓
RAG Evaluation
    ↓
Quality Gates
    ↓
PASS ─────────> Build succeeds
FAIL ─────────> Build fails
```

The CI job should fail if quality falls below configured thresholds.

This demonstrates that RAG quality is treated as an engineering requirement rather than a manual demonstration.

### Phase 3 Acceptance Criteria

Phase 3 is complete when:

- A golden dataset exists.
- Evaluation is reproducible.
- RAG metrics are calculated automatically.
- Results are saved.
- Quality thresholds are configurable.
- CI executes the evaluation.
- CI fails when quality drops below the defined threshold.

---

# 6. Suggested Technology Stack

| Area | Technology |
|---|---|
| Language | Python |
| Orchestration | LangChain or LangGraph |
| Vector Store | ChromaDB |
| Keyword Retrieval | BM25 |
| Semantic Retrieval | Embeddings + vector search |
| Re-ranking | Sentence Transformers Cross-Encoder |
| Evaluation | Ragas + custom evaluation |
| LLM | Ollama/local model or configurable API |
| UI | Streamlit or Gradio |
| Testing | pytest |
| CI | GitHub Actions |
| Configuration | YAML / environment variables |
| Logging | Python logging / structured logging |

Prefer free/open-source options for the core demonstration.

---

# 7. UI Plan

Create a simple professional UI with:

## Main Screen

- Document collection information
- Search/question input
- Answer
- Confidence/evidence indicator
- Citations
- Retrieved chunks
- Retrieval scores
- Response latency

## Debug / Evaluation Screen

Show:

- retrieval method
- BM25 results
- vector results
- merged candidates
- reranker results
- final context
- prompt version
- model
- evaluation scores

This second view is valuable for demonstrating the engineering depth of the project.

---

# 8. Demonstration Scenarios

Prepare at least five demo questions.

### Demo 1 — Direct Question

Ask something whose answer is explicitly present in a document.

Expected:

- correct answer
- exact citation

### Demo 2 — Semantic Question

Ask the same concept using different wording.

Expected:

- vector retrieval finds the correct evidence.

### Demo 3 — Keyword Question

Use an exact technical term or identifier.

Expected:

- BM25 provides strong retrieval.

### Demo 4 — Hybrid Question

Use a question where both semantic and keyword retrieval are useful.

Expected:

- hybrid retrieval improves the candidate set.
- re-ranking places the correct evidence first.

### Demo 5 — Unsupported Question

Ask something not contained in the corpus.

Expected:

```text
Insufficient Evidence
```

The system should refuse instead of hallucinating.

---

# 9. Testing Plan

Create tests for:

## Unit Tests

- document loading
- chunking
- metadata preservation
- embedding generation
- BM25 retrieval
- vector retrieval
- result fusion
- re-ranking
- citation generation
- evidence checking
- prompt loading

## Integration Tests

- ingestion → vector store
- query → retrieval
- retrieval → generation
- generation → citation
- complete RAG workflow

## Regression Tests

Run the golden dataset periodically.

## Negative Tests

Verify refusal for:

- unrelated questions
- missing information
- misleading context
- low-relevance retrieval
- empty document collections

---

# 10. Configuration

Use `.env` and configuration files.

Example:

```text
LLM_PROVIDER=ollama
LLM_MODEL=<configurable-model>
EMBEDDING_MODEL=<configurable-model>
VECTOR_STORE=chroma
TOP_K=10
RERANK_TOP_K=5
CHUNK_SIZE=700
CHUNK_OVERLAP=100
```

Never commit API keys or credentials.

Provide:

```text
.env.example
```

---

# 11. Recommended Development Order

Implement in this exact sequence:

1. Create project structure.
2. Add configuration system.
3. Implement document ingestion.
4. Implement chunking.
5. Implement embeddings.
6. Implement ChromaDB storage.
7. Implement basic vector retrieval.
8. Implement LLM answer generation.
9. Implement citations.
10. Build the Phase 1 UI.
11. Add BM25.
12. Implement hybrid retrieval.
13. Add cross-encoder re-ranking.
14. Add evidence/citation enforcement.
15. Add prompt versioning.
16. Add structured logging.
17. Create golden evaluation dataset.
18. Implement offline evaluation.
19. Add Ragas/custom metrics.
20. Define quality gates.
21. Add GitHub Actions CI.
22. Add regression tests.
23. Polish documentation.
24. Perform complete end-to-end demo.

---

# 12. Final Portfolio Story

The final project should be presented as:

> **Production-Grade RAG with Hybrid Retrieval, Re-Ranking, Citation Enforcement, Evaluation and CI Quality Gates**

The key progression to demonstrate is:

```text
Phase 1
Basic RAG
    ↓
Phase 2
Production Retrieval + Grounding
    ↓
Phase 3
Automated Evaluation + CI
```

The important portfolio message is:

**Do not just demonstrate that an LLM can answer questions from documents. Demonstrate that you can engineer, evaluate, observe, test, and continuously control the quality of a RAG system.**
