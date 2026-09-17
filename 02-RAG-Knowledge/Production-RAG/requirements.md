# Claude Code Prompt — RAG Documentation Assistant

---

## Role and Context

You are building a production-quality RAG (Retrieval-Augmented Generation) documentation assistant in Python using LangGraph and ChromaDB. This is a teaching project. Every concept must be modularised into its own file. Every function you define must be called somewhere in the application — there must be zero dead code. Before writing a single line of code, read this entire prompt.

---

## Strict Rules — Read Before Writing Any Code

1. **No dead code.** Every function, class, and method you define must be called. If you write a helper that nothing calls, delete it.
2. **One responsibility per file.** No file does two things. If it chunks, it does not embed. If it embeds, it does not search.
3. **No logic in demo scripts.** The files inside `demo/` are thin callers only. They import from the modules above and call one function. All logic lives in the modules.
4. **No magic numbers.** Every constant (`chunk_size`, `overlap`, `top_k`, `model name`, `collection name`, `chroma path`) is defined once in `config/settings.py` and imported everywhere it is used.
5. **All functions have type hints and docstrings.** This is a teaching project — the code must be self-documenting.
6. **Validate before finalising.** After writing all files, trace every function definition back to its call site. If any function is defined but never called, remove it or add the missing call.

---

## Project Structure — Create Exactly This

```
rag-doc-assistant/
├── docs/
│   ├── MCP_Documentation.md
│   └── DOCUMENTATION.md
├── config/
│   └── settings.py
├── chunking/
│   ├── character_splitter.py
│   ├── semantic_splitter.py
│   └── comparison.py
├── vectorstore/
│   ├── embedder.py
│   └── store.py
├── retrieval/
│   ├── semantic_search.py
│   └── hybrid_search.py
├── generation/
│   ├── prompt_builder.py
│   └── answer_generator.py
├── pipeline/
│   ├── state.py
│   ├── nodes.py
│   └── graph.py
├── demo/
│   ├── 01_chunking_comparison.py
│   ├── 02_ingest.py
│   └── 03_query.py
├── chroma_data/           ← auto-created by ChromaDB, in .gitignore
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── main.py
```

Do not create any file not listed here. Do not add `utils/`, `helpers/`, `tests/`, or any other folder.

---

## Document Corpus

The two source documents are placed in `docs/`. Their content determines how the chunking, embedding, and retrieval behave. You must understand their structure to write the chunkers correctly.

### Document 1 — `docs/MCP_Documentation.md`

This is a Markdown file. Its H2 sections are the semantic chunk boundaries:

```
## 1. What Is MCP (Model Context Protocol)?       — ~250 words, 1 code block, 2 tables
## 2. Why Build a Custom MCP Server?              — ~139 words, no code
## 3. Transport Options: Stdio vs Streamable HTTP — ~182 words, 1 code block
## 4. Project Architecture                        — ~118 words, 1 code block
## 5. Database Design                             — ~166 words, 6 SQL code blocks
## 6. The Four Tools — Implementation Details     — 461 words, OVERSIZED → H3 split required
## 7. Building the MCP Server with FastMCP        — ~190 words, 1 code block
## 8. Step-by-Step Build Order                    — ~234 words, no code
## 9. Running and Testing the Server              — ~135 words, 4 code blocks
## 10. What's Next — Extending This Server        — ~238 words, no code
```

Section 6 is the only section requiring **hybrid chunking** — it is 461 words (above the 400-word threshold) and contains 4 clean H3 subsections:

```
### Tool 1A: `get_patient_risk_summary`
### Tool 1B: `get_readmission_insights`
### Tool 2A: `get_database_schema`
### Tool 2B: `query_patient_database`
```

Split Section 6 at these four H3 boundaries. All other sections stay as single H2 chunks.

### Document 2 — `docs/DOCUMENTATION.md`

This is a 16-page Markdown document (exported from PDF). Its H2 sections:

```
## Project Overview
## Architecture Comparison
## Traditional Approach: Maps_Agent
## The Problem: Adding More Tools
## Modern Approach: MCP_Maps_Agent
## MCP Deep Dive: How It Works
## Key Differences and Benefits
## Running the Agents
```

All 8 sections are under 400 words. Apply pure H2 semantic chunking — no H3 splitting needed.

---

## File-by-File Specification

### `config/settings.py`

Define these constants. Nothing else — no functions, no classes:

```python
DOCS_PATH = "docs"
CHROMA_PATH = "chroma_data"
COLLECTION_NAME = "rag_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"

# Chunking
CHAR_CHUNK_SIZE = 500
CHAR_CHUNK_OVERLAP = 50
SEMANTIC_MAX_WORDS = 400      # sections above this trigger H3 splitting

# Retrieval
TOP_K = 5
```

---

### `chunking/character_splitter.py`

**Concept being taught:** Character splitting ignores meaning. It cuts at fixed character counts regardless of whether a code block, table, or sentence is mid-way through.

Define one dataclass and one function. Both must be used:

```python
@dataclass
class Chunk:
    content: str
    metadata: dict        # keys: doc_title, chunk_index, strategy, char_start, char_end
    word_count: int
    has_code_block: bool  # True if content contains ``` 
    has_table: bool       # True if content contains |---|
```

```python
def split_by_characters(text: str, doc_title: str, chunk_size: int, overlap: int) -> List[Chunk]:
    """
    Split text at fixed character intervals with overlap.
    Does not respect sentence, paragraph, or section boundaries.
    Produces the 'bad' chunks used in the comparison demo.
    """
```

Implementation notes:
- Slide a window of `chunk_size` characters across the text, stepping by `chunk_size - overlap`
- For each chunk, detect `has_code_block` by checking if ` ``` ` appears in the content
- Detect `has_table` by checking if `|---|` appears in the content
- Set `strategy = "character"` in metadata

---

### `chunking/semantic_splitter.py`

**Concept being taught:** Semantic chunking splits at meaning boundaries — `##` headers in Markdown. Hybrid chunking adds a word-count gate: sections above `SEMANTIC_MAX_WORDS` are split further at `###` headers.

Define one function. It must be used:

```python
def split_by_headers(text: str, doc_title: str, max_words: int) -> List[Chunk]:
    """
    Split Markdown text at ## header boundaries (semantic chunking).
    If any resulting section exceeds max_words, split it further at ### headers
    (hybrid chunking). This preserves code blocks and tables intact within
    their natural section boundary.
    """
```

Implementation notes:
- Use `re.split` on `\n## ` to get H2 sections
- For each H2 section, count words. If word count > `max_words`, split on `\n### `
- Each chunk's metadata must include: `doc_title`, `section_title` (the H2 header text), `subsection_title` (the H3 header text, or `None`), `chunk_index`, `strategy`, `word_count`
- Reuse the same `Chunk` dataclass from `character_splitter.py` — import it, do not redefine it
- Set `strategy = "semantic"` in metadata
- `has_code_block` and `has_table` detection same as character splitter

---

### `chunking/comparison.py`

**Concept being taught:** Running both strategies on the same document and surfacing the measurable differences — broken code blocks, mixed topics, size variance.

Define one dataclass and one function. Both must be used:

```python
@dataclass
class ComparisonResult:
    doc_title: str
    char_chunks: List[Chunk]
    semantic_chunks: List[Chunk]
    char_stats: dict     # total_chunks, avg_words, broken_code_blocks, broken_tables
    semantic_stats: dict # total_chunks, avg_words, broken_code_blocks, broken_tables
```

```python
def compare_strategies(doc_path: str) -> ComparisonResult:
    """
    Load a Markdown document, run both chunking strategies on it,
    compute statistics for each, and return a ComparisonResult.
    Called directly by demo/01_chunking_comparison.py.
    """
```

Implementation notes:
- Read the file, pass text to both `split_by_characters` and `split_by_headers`
- Use constants from `config/settings.py` for chunk size, overlap, max_words
- `broken_code_blocks`: count chunks where `has_code_block` is True AND the chunk does not contain a matching closing ` ``` ` — meaning the code block was cut in half
- `broken_tables`: count chunks where `has_table` is True AND the chunk contains `|` without a complete row structure
- Compute `avg_words` as mean word count across all chunks

---

### `vectorstore/embedder.py`

**Concept being taught:** Embedding converts text into a fixed-size vector. The model choice determines what semantic relationships are captured.

Define two functions. Both must be used:

```python
def load_embedding_model(model_name: str) -> SentenceTransformer:
    """
    Load and return the SentenceTransformer embedding model.
    Called once at ingest time and once at query time.
    """

def embed_chunks(chunks: List[Chunk], model: SentenceTransformer) -> List[List[float]]:
    """
    Embed a list of Chunk objects and return a list of embedding vectors.
    Each vector corresponds to the Chunk at the same index.
    Prints embedding progress: 'Embedding X chunks with model Y...'
    """
```

---

### `vectorstore/store.py`

**Concept being taught:** ChromaDB is a persistent vector store. `PersistentClient` writes to disk so the collection survives restarts. ChromaDB builds an HNSW index automatically — students see this as a deliberate tradeoff: simplicity over configurability.

Define three functions. All three must be used:

```python
def get_or_create_collection(chroma_path: str, collection_name: str) -> chromadb.Collection:
    """
    Create a PersistentClient pointing to chroma_path.
    Get or create the named collection.
    Print the path so students can see where data is stored:
    'ChromaDB collection at: ./chroma_data'
    """

def upsert_chunks(collection: chromadb.Collection, chunks: List[Chunk], embeddings: List[List[float]]) -> None:
    """
    Insert chunks and their embeddings into the collection.
    Each document ID is: f"{chunk.metadata['doc_title']}_{chunk.metadata['chunk_index']}"
    Store the full metadata dict as ChromaDB metadata.
    Store chunk.content as the document text.
    Print: 'Upserted X chunks into collection Y'
    """

def load_collection(chroma_path: str, collection_name: str) -> chromadb.Collection:
    """
    Load an existing ChromaDB collection from disk.
    Raise a clear RuntimeError if the collection does not exist yet:
    'Collection not found. Run demo/02_ingest.py first.'
    """
```

---

### `retrieval/semantic_search.py`

**Concept being taught:** Semantic search embeds the query and finds the most similar chunks by cosine distance. Works well for conceptual questions. Struggles with exact function names and error codes.

Define one dataclass and one function. Both must be used:

```python
@dataclass
class RetrievedChunk:
    content: str
    metadata: dict
    score: float          # distance score from ChromaDB (lower = more similar)
    rank: int             # 1-indexed position in results
```

```python
def search(query: str, collection: chromadb.Collection, model: SentenceTransformer, top_k: int) -> List[RetrievedChunk]:
    """
    Embed the query, query the ChromaDB collection, return top_k results
    as RetrievedChunk objects ranked by similarity score.
    """
```

---

### `retrieval/hybrid_search.py`

**Concept being taught:** Hybrid search fuses keyword (BM25) and vector search. Exact terms like `get_patient_risk_summary`, `PRAGMA table_info`, `FastMCP` are found by BM25. Conceptual queries are found by vector search. Reciprocal Rank Fusion (RRF) merges the two ranked lists.

Define one function. It must be used:

```python
def search(query: str, collection: chromadb.Collection, model: SentenceTransformer, top_k: int) -> List[RetrievedChunk]:
    """
    Run BM25 keyword search over all chunk texts in the collection.
    Run vector similarity search via the collection.
    Merge both ranked lists using Reciprocal Rank Fusion (RRF):
        rrf_score = 1/(rank_bm25 + 60) + 1/(rank_vector + 60)
    Return top_k results sorted by RRF score descending.
    Use rank_bm25 score = 0 for chunks not found by BM25 and vice versa.
    """
```

Implementation notes:
- Use `rank_bm25` library for BM25. Install via `pip install rank-bm25`
- Fetch all documents from the collection to build the BM25 corpus: `collection.get(include=["documents", "metadatas"])`
- Vector search: embed the query and call `collection.query()`
- The function signature is identical to `semantic_search.search` — the pipeline can swap between them by changing one import

---

### `generation/prompt_builder.py`

**Concept being taught:** The system prompt is where strict grounding and non-hallucination are enforced. The retrieved chunks are the only source the model is allowed to use. The citation format is designed so the engineer can trace every claim back to a document section.

Define one dataclass and one function. Both must be used:

```python
@dataclass
class PromptMessages:
    system: str
    user: str
```

```python
def build_prompt(query: str, chunks: List[RetrievedChunk]) -> PromptMessages:
    """
    Build a system prompt and user message from the query and retrieved chunks.

    System prompt must include these exact instructions:
    - Answer ONLY using the information in the provided document chunks.
    - If the answer is not present in the chunks, respond with:
      'I could not find an answer to this question in the provided documentation.'
    - Do not infer, guess, or use external knowledge.
    - For every claim in your answer, cite the source using this format:
      [Source: <doc_title>, Section: <section_title>]

    User message format:
    --- Retrieved Documentation ---
    [Chunk 1 - doc_title | section_title]
    <chunk content>

    [Chunk 2 - doc_title | section_title]
    <chunk content>
    ... (all top_k chunks)
    ---
    Question: <query>
    """
```

---

### `generation/answer_generator.py`

**Concept being taught:** The LLM is the final step — it reads the grounded prompt and generates a cited answer. If the answer is not in the docs, it refuses rather than hallucinating.

Define one dataclass and one function. Both must be used:

```python
@dataclass
class Answer:
    text: str
    citations: List[str]    # extracted citation strings from the answer text
    query: str
    chunks_used: int
```

```python
def generate(prompt: PromptMessages, query: str, chunks_used: int) -> Answer:
    """
    Call the Anthropic Claude API with the prompt messages.
    Parse citation strings from the response (lines matching '[Source: ..., Section: ...]').
    Return an Answer dataclass.
    Model: claude-3-5-haiku-20241022
    Max tokens: 1024
    Read ANTHROPIC_API_KEY from environment variables using python-dotenv.
    """
```

---

### `pipeline/state.py`

**Concept being taught:** LangGraph passes a single shared state dictionary between nodes. `TypedDict` gives it a typed schema so every node knows exactly what keys exist.

Define one TypedDict. It must be imported by `nodes.py` and `graph.py`:

```python
class RAGState(TypedDict):
    query: str
    retrieved_chunks: List[RetrievedChunk]
    prompt: PromptMessages
    answer: Answer
    error: str          # empty string if no error; populated if a node fails
```

---

### `pipeline/nodes.py`

**Concept being taught:** Each LangGraph node is a pure function that takes state, does one job, and returns an updated state dict. Nodes never call each other — the graph wires them.

Define three functions. All three must be registered in `graph.py`:

```python
def retrieve_node(state: RAGState) -> dict:
    """
    Load the ChromaDB collection.
    Load the embedding model.
    Run hybrid_search.search() with query from state.
    Return: {"retrieved_chunks": [...]}
    On error: return {"error": "Retrieval failed: <message>"}
    """

def build_prompt_node(state: RAGState) -> dict:
    """
    Call prompt_builder.build_prompt() with query and retrieved_chunks from state.
    Return: {"prompt": <PromptMessages>}
    On error: return {"error": "Prompt build failed: <message>"}
    """

def generate_node(state: RAGState) -> dict:
    """
    Call answer_generator.generate() with prompt from state.
    Return: {"answer": <Answer>}
    On error: return {"error": "Generation failed: <message>"}
    """
```

---

### `pipeline/graph.py`

**Concept being taught:** LangGraph `StateGraph` wires nodes into a directed graph. The flow is linear here: retrieve → build_prompt → generate. Students see the full pipeline in under 25 lines.

Define two functions. Both must be used:

```python
def build_rag_graph() -> CompiledGraph:
    """
    Build and compile the LangGraph StateGraph:
    START → retrieve_node → build_prompt_node → generate_node → END
    Add a conditional edge after retrieve_node: if state["error"] is not empty,
    route directly to END instead of continuing.
    Return the compiled graph.
    """

def run_query(query: str) -> Answer:
    """
    Build the graph, invoke it with initial state {"query": query, "error": ""},
    and return the Answer from the final state.
    If state["error"] is not empty after the run, raise RuntimeError(state["error"]).
    """
```

---

### `demo/01_chunking_comparison.py`

This file contains zero logic. It imports and calls one function, then prints the results.

```python
"""
Demo 1: Chunking Strategy Comparison
Shows why character splitting fails on technical documentation
and how semantic chunking preserves meaning boundaries.
"""
from chunking.comparison import compare_strategies

def main():
    # Run comparison on the MCP documentation (richest structure for demo)
    result = compare_strategies("docs/MCP_Documentation.md")
    print_comparison(result)

def print_comparison(result):
    # Print a formatted side-by-side comparison including:
    # - Total chunk count for each strategy
    # - Average words per chunk for each strategy
    # - Number of broken code blocks for each strategy
    # - Number of broken tables for each strategy
    # - 3 example chunks from character splitting showing the problems:
    #     - A chunk that cuts a code block in half
    #     - A chunk that mixes content from two different sections
    # - 3 example chunks from semantic splitting showing clean boundaries:
    #     - Each chunk starts with its section title
    #     - Code blocks are complete
    #     - Word count is within expected range
    # Use box-drawing characters for the table borders (─ │ ┌ ┐ └ ┘ ├ ┤)
    # Label the character chunks column as "CHARACTER SPLITTER (bad)"
    # Label the semantic chunks column as "SEMANTIC SPLITTER (good)"
    pass

if __name__ == "__main__":
    main()
```

Implement `print_comparison` fully. The `pass` is a placeholder showing intent.

---

### `demo/02_ingest.py`

This file contains zero logic. It orchestrates the ingestion pipeline by calling module functions in sequence.

```python
"""
Demo 2: Document Ingestion Pipeline
Loads documents, applies semantic chunking, embeds chunks,
and persists them to ChromaDB on disk.
"""
from config.settings import DOCS_PATH, CHROMA_PATH, COLLECTION_NAME, EMBED_MODEL, SEMANTIC_MAX_WORDS
from chunking.semantic_splitter import split_by_headers
from vectorstore.embedder import load_embedding_model, embed_chunks
from vectorstore.store import get_or_create_collection, upsert_chunks
import os

def main():
    # 1. Discover all .md files in DOCS_PATH
    # 2. For each document: read text, call split_by_headers, collect chunks
    # 3. Load embedding model once
    # 4. Embed all chunks in one batch
    # 5. Get or create ChromaDB collection
    # 6. Upsert all chunks with their embeddings
    # 7. Print final summary: total documents, total chunks, chroma_data path
    pass

if __name__ == "__main__":
    main()
```

Implement `main` fully.

---

### `demo/03_query.py`

This file accepts a CLI argument and runs the full LangGraph pipeline.

```python
"""
Demo 3: RAG Query Pipeline
Run a question through the full RAG pipeline:
retrieve → build prompt → generate answer with citations.

Usage:
    python demo/03_query.py "How does FastMCP register a tool?"
    python demo/03_query.py "What is the difference between Stdio and Streamable HTTP?"
    python demo/03_query.py "What is the rate limit on the quantum API?"
"""
import sys
from pipeline.graph import run_query

def main():
    # Read query from sys.argv[1]
    # If no argument provided, print usage and exit with code 1
    # Call run_query(query)
    # Print the answer with formatting:
    #   - Section header: "ANSWER"
    #   - The answer text
    #   - Section header: "CITATIONS"
    #   - Each citation on its own line
    #   - Section header: "CHUNKS USED"
    #   - The number of chunks retrieved
    pass

if __name__ == "__main__":
    main()
```

Implement `main` fully.

---

### `main.py`

The single entry point that runs the entire demo in sequence.

```python
"""
RAG Documentation Assistant — Full Demo
Runs all three demo scripts in sequence with explanatory banners.

Usage: python main.py
"""
from demo import chunking_comparison, ingest, query as query_demo

def print_banner(title: str) -> None:
    """Print a formatted section banner with box-drawing characters."""

def main():
    print_banner("DEMO 1 — CHUNKING STRATEGY COMPARISON")
    # explain in 2 lines what the student is about to see
    chunking_comparison.main()

    print_banner("DEMO 2 — DOCUMENT INGESTION")
    # explain in 2 lines what the student is about to see
    ingest.main()

    print_banner("DEMO 3 — RAG QUERY PIPELINE")
    # Run with a hardcoded test question that demonstrates citation
    # Use: "How does FastMCP register a tool with the MCP server?"
    # explain in 2 lines what the student is about to see
    query_demo.main_with_query("How does FastMCP register a tool with the MCP server?")

if __name__ == "__main__":
    main()
```

Add a `main_with_query(query: str)` function to `demo/03_query.py` that accepts the query as a parameter instead of reading from `sys.argv`. The existing `main()` in `03_query.py` calls `main_with_query(sys.argv[1])`.

---

### `requirements.txt`

```
anthropic
chromadb
sentence-transformers
langgraph
langchain-core
rank-bm25
python-dotenv
```

---

### `.env.example`

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

---

### `.gitignore`

```
chroma_data/
.env
__pycache__/
*.pyc
.DS_Store
```

---

### `README.md`

Write a README with these sections:
1. **What this project teaches** — list the 5 RAG concepts demonstrated
2. **Setup** — `pip install -r requirements.txt`, copy `.env.example` to `.env`, add API key
3. **Add your documents** — place `.md` files in `docs/`
4. **Run the full demo** — `python main.py`
5. **Run individual demos** — commands for each of the three demo scripts
6. **Project structure** — the folder tree with one-line descriptions
7. **Upgrading to production** — note that ChromaDB's HNSW index is automatic here; for configurable indexing, swap `vectorstore/store.py` for Qdrant with explicit `m` and `ef_construct` params — no other file changes required

---

## What the Chunking Comparison Output Must Show

When `demo/01_chunking_comparison.py` runs, the terminal output must make the problem viscerally clear. Here is the required output structure:

```
┌─────────────────────────────────────────────────────────────────┐
│           CHUNKING STRATEGY COMPARISON                          │
│           Document: MCP_Documentation.md                        │
└─────────────────────────────────────────────────────────────────┘

STATISTICS
─────────────────────────────────────────────────────────────────
                        CHARACTER           SEMANTIC
                        SPLITTER (bad)      SPLITTER (good)
─────────────────────────────────────────────────────────────────
Total chunks            ~14                 14
Avg words/chunk         ~71                 ~162
Broken code blocks      X                   0
Broken tables           X                   0
─────────────────────────────────────────────────────────────────

CHARACTER SPLITTER — 3 Problem Examples
─────────────────────────────────────────────────────────────────
[Chunk 4 | 500 chars | has_code_block=True | BROKEN]
...content showing code block cut in half...

[Chunk 7 | 500 chars | MIXES: Database Design + Tool Details]
...content showing two unrelated topics...
─────────────────────────────────────────────────────────────────

SEMANTIC SPLITTER — 3 Clean Examples
─────────────────────────────────────────────────────────────────
[Section: "3. Transport Options" | 182 words | code intact]
...first 200 chars of the section...

[Section: "Tool 1A: get_patient_risk_summary" | 146 words | table intact]
...first 200 chars of the section...
─────────────────────────────────────────────────────────────────
```

The actual numbers for broken code blocks and broken tables come from the real `ComparisonResult` — do not hardcode them.

---

## Non-Hallucination Test

The `demo/03_query.py` must work correctly for both these queries:

**Query that IS in the docs:**
```
python demo/03_query.py "How does FastMCP register a tool with the MCP server?"
```
Expected: A specific cited answer referencing Section 7 of MCP_Documentation.md.

**Query that is NOT in the docs:**
```
python demo/03_query.py "What is the rate limit on the Stripe API?"
```
Expected output must contain:
```
I could not find an answer to this question in the provided documentation.
```
No citations. No hallucinated answer.

---

## Final Validation Checklist — Run This Before Finishing

Before declaring the project complete, trace every function:

```
character_splitter.py  → split_by_characters()    called in: comparison.py
semantic_splitter.py   → split_by_headers()       called in: comparison.py, demo/02_ingest.py
comparison.py          → compare_strategies()     called in: demo/01_chunking_comparison.py
embedder.py            → load_embedding_model()   called in: demo/02_ingest.py, pipeline/nodes.py
embedder.py            → embed_chunks()           called in: demo/02_ingest.py
store.py               → get_or_create_collection() called in: demo/02_ingest.py
store.py               → upsert_chunks()          called in: demo/02_ingest.py
store.py               → load_collection()        called in: pipeline/nodes.py
semantic_search.py     → search()                 called in: pipeline/nodes.py (optional path)
hybrid_search.py       → search()                 called in: pipeline/nodes.py (primary path)
prompt_builder.py      → build_prompt()           called in: pipeline/nodes.py
answer_generator.py    → generate()               called in: pipeline/nodes.py
pipeline/state.py      → RAGState                 used in: nodes.py, graph.py
pipeline/nodes.py      → retrieve_node()          registered in: graph.py
pipeline/nodes.py      → build_prompt_node()      registered in: graph.py
pipeline/nodes.py      → generate_node()          registered in: graph.py
pipeline/graph.py      → build_rag_graph()        called in: run_query()
pipeline/graph.py      → run_query()              called in: demo/03_query.py, main.py
demo/01               → main()                    called in: main.py
demo/02               → main()                    called in: main.py
demo/03               → main()                    entry point via __main__
demo/03               → main_with_query()         called in: demo/03 main(), main.py
print_banner()        → defined in main.py        called 3 times in main.py
```

If any function in this list is missing a call site, add the call or remove the function.

---

## Place the Two Documents

After generating all code files, create the two document files in `docs/`:

- `docs/MCP_Documentation.md` — copy the exact content of the MCP Healthcare Patient Records document
- `docs/DOCUMENTATION.md` — copy the exact content of the AI Agents Traditional vs MCP document

The content of these files is what gets chunked, embedded, and queried. Without them, `demo/02_ingest.py` will find no documents.
