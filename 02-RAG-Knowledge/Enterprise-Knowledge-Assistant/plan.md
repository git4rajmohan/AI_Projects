# Plan: Enterprise Knowledge Assistant (LlamaIndex + Cognee + Qdrant + Ollama)

Local-first RAG app. Documents → Cognee (knowledge/graph processing + configured vector backend) →
Qdrant (vectors) → LlamaIndex (orchestration) → Ollama (LLM: Ollama Cloud `gpt-oss:120b` via a
pluggable provider; embeddings: local `nomic-embed-text`) → Streamlit UI with grounded, cited answers.

Decisions locked in with user:
- Skip cloning `policy-rag-app` reference repo — the 11 PDFs already exist in `data/documents/`.
- Ollama + Qdrant are NOT yet installed/running — plan includes first-time setup for both.
- LLM: Ollama Cloud, model tag `gpt-oss:120b`, called directly against `https://ollama.com/api` with
  an API key (native Ollama format, NOT OpenAI format).
- Embeddings: local Ollama daemon (`http://localhost:11434`), model `nomic-embed-text` (Ollama Cloud
  has no embedding models).
- **Single authoritative ingestion path**: Cognee owns document processing, knowledge-graph
  construction, embedding generation, and writes into its *configured* vector backend (Qdrant).
  Do not hard-code the assumption "Cognee writes vectors → Qdrant" as a fixed pipeline step we
  re-implement — it's Cognee's adapter behavior, verified against the installed version. There is
  no second embed→insert pipeline anywhere in the app.
- `app/vectorstore/qdrant_manager.py` is a **thin operational/read layer only**: health check,
  collection existence/info, vector count, embedding-dimension check, delete/reset. It never
  independently embeds or inserts documents.
- **LLM provider abstraction**: `app/llm/providers/base.py` defines an `LLMProvider` interface;
  `LocalOllamaProvider` and `OllamaCloudProvider` implement it. The application selects one via
  `.env` config (`OLLAMA_PROVIDER=local|cloud`). No provider-specific logic lives inside
  `llamaindex_engine.py` or any retrieval code.
- Must verify whether `llama-index-llms-ollama`'s `Ollama` class supports a custom `host` +
  `Authorization` header out of the box; if not, `OllamaCloudProvider` wraps the raw `ollama` Python
  client directly. Either way this stays isolated behind the `LLMProvider` interface.
- **Security**: real API keys/secrets only ever go in `.env` (gitignored). `plan.md`, `instructions.md`,
  README, source, and tests use placeholders like `<your-ollama-api-key>` — never a literal key value.

---

## Phase 0 — Project Scaffolding
- [x] Create the directory/file skeleton exactly per instructions.md §37, plus `app/llm/providers/`: `app/{config,ui,ingestion,retrieval,knowledge,vectorstore,llm,llm/providers,models}`, `data/metadata/`, `logs/`, `tests/`, `scripts/`
- [x] Create empty `__init__.py` in each `app` subpackage
- [x] Create `.gitignore` (venv, `.env`, `logs/`, `data/metadata/*.json` if generated, `__pycache__`, Qdrant storage dir)
- [x] Create `.env.example` with keys: `OLLAMA_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_EMBED_MODEL`, `OLLAMA_CLOUD_BASE_URL`, `OLLAMA_API_KEY=<your-ollama-api-key>`, `OLLAMA_LLM_MODEL`, `QDRANT_URL`, `QDRANT_COLLECTION`, `QDRANT_API_KEY`, `TOP_K`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `DATA_DIR`, `DOCUMENT_DIR`, `METADATA_DIR`, `LOG_LEVEL` — placeholder values only, never a real key
- [x] Copy `.env.example` → `.env` (local, gitignored) and fill in the real `OLLAMA_API_KEY` there only
- **Verify:** `list_dir` shows full tree matching §37; `.env` is gitignored (`git status` shows it untracked/ignored); confirm no real key exists anywhere outside `.env`

## Phase 1 — Python Environment & Local Services
- [x] Create venv: `python -m venv .venv`, activate, `python -m pip install --upgrade pip` (Python 3.11.9, pip 26.2.1)
- [x] Install minimal bootstrap deps only: `python-dotenv`, `requests`, `ollama` (python client), `qdrant-client` (+ pytest for later phases)
- [x] Install/verify local Ollama daemon is running (`ollama list`); pull `nomic-embed-text` (already present, 27 local models)
- [x] Obtain Ollama Cloud API key (ollama.com/settings/keys) and confirm `gpt-oss:120b` is reachable via a raw `POST https://ollama.com/api/chat` call with `Authorization: Bearer <key>` (key from AI_GraphRAG .env; chat returned "OK")
- [x] Download Windows Qdrant server binary release, place at `qdrant\qdrant.exe`, start it, confirm `storage\` is created (Qdrant v1.19.1 running on localhost:6333)
- [x] Write `scripts/check_services.py`: checks (a) local Ollama `/api/tags`, (b) `nomic-embed-text` present, (c) Ollama Cloud reachability + `gpt-oss:120b` availability, (d) Qdrant `GET /` or `/collections`, prints real ✅/❌ per check — no fabricated "Connected"
- **Verify:** run `python scripts/check_services.py` → all 4 checks pass with the real local processes running

## Phase 2 — Configuration Layer
- [x] Implement `app/config/settings.py`: a `Settings` dataclass/pydantic model loading all `.env` keys via `python-dotenv`, with typed fields (no hard-coded defaults for model names/paths — read from env, fall back to instructions.md examples only as defaults)
- [x] Add `tests/test_configuration.py`: `test_configuration_loading` (reads a temp `.env`), `test_default_configuration` (defaults applied when env var absent)
- **Verify:** `pytest tests/test_configuration.py -v` passes

## Phase 3 — Document Inventory & Metadata
- [x] Implement `app/ingestion/metadata.py`: `DocumentMetadata` schema (document_id, filename, document_type, department, version="Unknown", upload_date, source_path, file_hash, status) + SHA-256 hashing function
- [x] Implement `app/ingestion/document_manager.py`: scans `data/documents/`, computes hashes, writes/reads metadata JSON to `data/metadata/`, exposes duplicate-detection by hash
- [x] Add `tests/test_ingestion.py::test_metadata_creation` and `test_duplicate_detection` (use 2 real PDFs from the corpus, no mocked file content)
- **Verify:** run a small script/test that inventories the 11 existing PDFs and prints real metadata for each; `pytest tests/test_ingestion.py -k metadata` passes

## Phase 4 — Qdrant Connectivity & Thin Manager
- [x] Implement `app/vectorstore/qdrant_manager.py` as a **thin operational layer only**: `health_check()`, `collection_exists(name)`, `get_collection_info(name)` (vector count, embedding dimension), `delete_collection(name)` / `reset()` — no embedding logic, no manual vector insertion
- [x] Confirm this module never independently embeds documents or writes vectors — its only job is to observe/manage whatever collection Cognee (or later LlamaIndex reads) populates
- [x] Add `tests/test_qdrant.py`: `test_health_check`, `test_collection_lifecycle` (create empty test collection via raw qdrant-client, verify existence/info, delete it) — against the real local Qdrant instance, no vector insertion pipeline under test here
- **Verify:** `pytest tests/test_qdrant.py -v` passes; `python -c "from app.vectorstore.qdrant_manager import health_check; print(health_check())"` reports real connectivity

## Phase 5 — Cognee Setup & Subset Ingestion Test (1–2 PDFs)
- [x] Inspect installed Cognee version's actual API (`pip show cognee`, check current docs) before writing code — record findings as a code comment/README note, not assumptions
- [x] Add `cognee` to deps; configure Cognee's LLM provider (via the `LLMProvider` abstraction from Phase 7, built here if not yet available) and embedding provider (local Ollama), and point Cognee's *configured* vector backend at the same local Qdrant instance — do not assume a fixed "Cognee writes to Qdrant" pipeline shape, follow the installed adapter's actual config surface
- [x] Implement `app/knowledge/cognee_manager.py` with a narrow interface: `add_documents(paths)`, `process()`, `get_status()` — all Cognee-specific calls isolated here; this is the **sole** ingestion/embedding entry point in the app
- [x] Test-run ingestion against **1–2 PDFs only** (e.g. `holiday-schedule.pdf`, `benefits-overview.pdf`) — do not run all 11 yet
- [x] Verify, using real values only: documents processed, graph nodes created, graph relationships created (query Cognee's own store), Qdrant collection now exists (via `qdrant_manager.collection_exists`), real vector count, real embedding dimension — do not assume Cognee/Qdrant compatibility just because both claim to support it
- **Verify (DONE 2026-09-07):** cognee 1.4.2 + cognee-community-vector-adapter-qdrant 0.4.0. Subset run (holiday-schedule.pdf + benefits-overview.pdf) via `scripts/cognee_subset_test.py`: graph **208 nodes / 526 relationships** (Entity 158, EntityType 30, DocumentChunk 9, TextSummary 9, TextDocument 2); 6 Qdrant collections all green (Entity_name=158, EdgeType_relationship_name=527, EntityType_name=30, DocumentChunk_text=9, TextSummary_text=9, TextDocument_name=2), **768-dim** named vectors (nomic-embed-text, dimension probed from a real /api/embed call). LLM = Ollama Cloud **OpenAI-compatible `https://ollama.com/v1`** surface (cognee's 'ollama' provider is an AsyncOpenAI client — native /api does NOT work). Embeddings = local daemon `/api/embed`. Cognee storage redirected out of site-packages via SYSTEM_ROOT_DIRECTORY/DATA_ROOT_DIRECTORY into `data/cognee/`. Multi-user access control requires `VECTOR_DATASET_DATABASE_HANDLER=qdrant` (handler ships in the adapter package). Graph reads require per-dataset context (`set_database_global_context_variables(dataset.id, user.id)`). Graph edge indexing initially failed on cold-embedding timeouts; succeeded once local daemon was warm. All 13 existing tests still pass.

## Phase 6 — Full Corpus Ingestion via Cognee
- [x] Extend `cognee_manager.py` to process all 11 PDFs, wired through `document_manager.py`'s duplicate-detection so re-runs don't reprocess unchanged files — implemented as `CognifyManager.ingest_all(paths)` consulting an ingested-hash ledger (`data/metadata/ingested.json`); Phase 5's 2-PDF subset migrated into the ledger via `seed_ledger`
- [x] Confirm this remains the single authoritative ingestion path — no separate embed→insert step is added anywhere else in the app (grep-verified: `import cognee` only in `cognee_manager.py`; `qdrant_client` only in the thin ops layer; no upsert/point-writing in `app/`)
- [x] Log real processing counts (`Documents processed`, `Chunks created`, `Entities extracted`, `Relationships extracted`) — never fabricate — `scripts/ingest_corpus.py` prints real counts from graph + Qdrant
- **Verify (DONE 2026-09-07):** full run processed 9 new PDFs (2 skipped via ledger from Phase 5), ~26 min via Ollama Cloud `gpt-oss:120b`. FINAL: graph **2137 nodes / 5340 relationships** (Entity 1664, EntityType 200, DocumentChunk 131, TextSummary 131, TextDocument 11 — all 11 docs); Qdrant Entity_name=1630, EdgeType_relationship_name=5385, EntityType_name=188, DocumentChunk_text=131, TextSummary_text=125, TextDocument_name=11 (768-dim). Duplicate re-run: **11/11 skipped, 0 processed, 0.0s**. All 13 tests pass.

### Phase 6 root-cause fixes (both in `cognee_manager.py`, both required)
1. **Cognee's bundled `summarize_content.txt` prompt breaks reasoning models**: it says "Output two sections only" (markdown) while instructor demands JSON — `gpt-oss:120b` obeyed the "developer-style" markdown instruction and every `SummarizedContent` JSON parse failed, killing the whole pipeline. `_fix_summarize_prompt()` rewrites the prompt (in the cognee install dir, via `cognee.root_dir.get_absolute_path`) to request a JSON `{"summary": ...}` matching cognee's own `SummarizedContent` schema; original saved as `.orig` backup, patch idempotent.
2. **Qdrant 408 saturation**: cognee's default `EMBEDDING_MAX_CONCURRENT_DATA_POINTS=150` floods local Qdrant with concurrent upserts → `408 Request Timeout` on even a `collection_exists` probe, and each failed pipeline run rolls back provenance so the next run re-does ALL LLM extraction. Fix: `os.environ.setdefault("EMBEDDING_MAX_CONCURRENT_DATA_POINTS", "30")` in `configure()` — pipeline then completed cleanly.

### Phase 6 operational notes
- Failed runs roll back provenance ⇒ next run re-extracts everything (LLM calls again). The ledger only marks a file after `process()` fully succeeds — correct behavior, but a mid-run failure costs a full re-extract. The two fixes above eliminated the failure modes.
- Ollama Cloud 429 (`too many concurrent requests`) is routine under cognee's concurrency; its tenacity backoff absorbs them — don't kill runs over 429 noise.
- Transient `httpx.ReadError` from Qdrant mid-bulk-upsert happened once; re-run recovered.
- Graph file lock (`Could not set lock ... .lbug`, Windows error 33) can appear if a check script runs while another python process holds the Ladybug DB — close other processes first.

## Phase 7 — LlamaIndex Basic RAG (Vector Only)
- [x] Install `llama-index`, `llama-index-llms-ollama`, `llama-index-embeddings-ollama`, `llama-index-vector-stores-qdrant` — verify each package's current API against installed version before coding
- [x] Implement `app/llm/providers/base.py`: `LLMProvider` interface (e.g. `get_llm()`, `get_embedding_model()`)
- [x] Implement `app/llm/providers/local_ollama_provider.py` (`LocalOllamaProvider`) and `app/llm/providers/ollama_cloud_provider.py` (`OllamaCloudProvider` — direct API-key call to `https://ollama.com/api`, native format; falls back to a `CustomLLM` subclass if `llama-index-llms-ollama`'s built-in class can't be configured with a custom `host`+headers)
- [x] Implement `app/llm/ollama_manager.py` as a thin factory: reads `OLLAMA_PROVIDER` from `Settings` and returns the selected provider instance — no provider-specific branching anywhere else in the app
- [x] Implement `app/retrieval/vector_retriever.py`: `VectorRetriever.retrieve(query)` → returns document/chunk/score/metadata/source (per §24), reading from the Qdrant collection populated in Phase 5/6
- [x] Implement `app/retrieval/llamaindex_engine.py`: wires embedding model + LLM (both obtained from `ollama_manager`'s selected provider) + `QdrantVectorStore` into a LlamaIndex query engine — contains zero local-vs-cloud logic itself
- [x] Add `tests/test_retrieval.py::test_relevant_question` using a real question against the real indexed corpus (e.g. "How many annual leave days do employees receive?")
- **Verify (DONE 2026-09-07):** llama-index 0.14.24 / llms-ollama 0.11.0 / embeddings-ollama 0.10.0 / vector-stores-qdrant 0.10.3. KEY FINDING: llama-index `Ollama` class forwards `headers` to the underlying `ollama.Client` and speaks native format → `Ollama(base_url="https://ollama.com", headers={"Authorization": "Bearer <key>"})` works for `complete()` AND `chat()` — NO CustomLLM fallback needed (verified live). Embeddings stay on the local daemon for both providers (cloud plan has none) → `get_embedding_model()` lives in the base class as shared default. §23 DESIGN DECISION: Cognee's Qdrant payloads have NO filename and a non-LlamaIndex schema (`text` named vector + internal fields, no `_node_content`) → **Design C adapter layer**: `VectorRetriever` queries Cognee's `DocumentChunk_text` collection directly (raw qdrant-client, read-only) and LlamaIndex synthesizes over the evidence. REAL PROVENANCE FOUND: Cognee graph records `DocumentChunk --is_part_of--> TextDocument` (131 edges/11 docs) with `TextDocument.name` = doc stem → `CognifyManager.get_chunk_document_map()` resolves chunk→filename, so citations are REAL (e.g. `pto-and-leave-policy.pdf`), never guessed; unresolvable chunks say "unknown". `scripts/ask_question.py` end-to-end: real grounded answer (10/15/20 vacation days by tenure) + real sources. `pytest tests/` 18/18 pass (5 new retrieval tests incl. unknown-question not-found + source-metadata validation).

## Phase 8 — Citations & Unknown-Question Handling
- [x] Implement citation extraction from retrieved LlamaIndex source nodes only (never LLM-generated) — filename always, page only if present in real node metadata — `Citation` dataclass + `RetrievalResult.citations` in `llamaindex_engine.py`; built solely from retrieved hits (`hit.metadata.get("page")`, which Cognee chunks never carry → page omitted per §27, never fabricated)
- [x] Implement the grounded system prompt from instructions.md §25 in `llamaindex_engine.py` — done in Phase 7 (GROUNDED_PROMPT is §25 verbatim)
- [x] Add `tests/test_retrieval.py::test_no_relevant_information` using "What is the company's private jet travel policy?" — assert response indicates not-found — done in Phase 7, re-verified
- [x] Add `tests/test_retrieval.py::test_source_metadata` — assert every citation filename exists in `data/documents/` — done in Phase 7, extended in Phase 8 to assert `citation.page is None` (no fabricated pages) and fixed a stale skip-string
- **Verify (DONE 2026-09-08):** `pytest tests/test_retrieval.py -v` → 5/5 pass against real services (real citations e.g. `pto-and-leave-policy.pdf`; unknown-question test passes with explicit not-found; zero fabricated page numbers). Fixed a Windows UnicodeEncodeError in test printing via `sys.stdout.reconfigure(encoding="utf-8")` in `tests/conftest.py`; full suite 18/18 green.

## Phase 9 — Graph Retrieval (Cognee)
- [x] Implement `app/retrieval/graph_retriever.py`: `GraphRetriever.retrieve(query)` calling the installed Cognee version's actual search/query API — returns entities, relationships, supporting evidence, source metadata
- [x] Add `tests/test_retrieval.py::test_hybrid_retrieval` groundwork — verify graph retriever alone returns real (non-empty, non-fabricated) results for a relationship question (e.g. "Which policy governs remote work?") — implemented as `test_graph_retrieval_returns_relationships`
- **Verify (DONE 2026-09-08):** `pytest tests/test_retrieval.py -v` → 6/6 pass (new graph test included); full suite **19/19 green**. KEY FINDING: cognee 1.4.2's `cognee.search(SearchType.GRAPH_COMPLETION)` runs an LLM completion over graph context — returns a synthesized string, NOT raw triplets, so it's wrong for evidence fusion. The retrieval primitive beneath it is `cognee.modules.retrieval.utils.brute_force_triplet_search` (query → embedding → vector search over graph collections → ID-filtered graph projection → ranked `Edge` objects) — `GraphRetriever` calls it directly inside `set_database_global_context_variables(dataset.id, user.id)`: REAL triplets, no extra LLM call, single-pipeline rule intact. Edge shape verified live: `edge.attributes["relationship_name"]`, `edge.node1/node2.attributes["name"|"type"|"description"]`, distance in `attributes["vector_distance"]` as a **1-element list** (e.g. `[0.1097]`) — must unwrap element 0 before `float()`. Real output for "Which policy governs remote work?": 5 triplets (`remote work policy --is_a--> policy` d=0.110, `remote work policy --defines_arrangement--> fully remote` d=0.114, …). PROVENANCE DECISION: graph triplets name entities, not documents — evidence is labeled `source="knowledge graph"` rather than guessed filenames; real per-document citations remain VectorRetriever's job (its chunk→doc map is graph-derived). CONFIG GOTCHA: `configure()` must run (sets `SYSTEM_ROOT_DIRECTORY` env) BEFORE the first cognee import/config access in the process, else cognee's relational engine resolves to site-packages paths and `get_default_user` fails with `sqlite3.OperationalError: unable to open database file`. `GraphRetriever.__init__` therefore calls `configure()` and `_retrieve_async` re-imports inside the async body.

## Phase 10 — Hybrid Retrieval
- [x] Implement `app/retrieval/hybrid_retriever.py`: `HybridRetriever.retrieve(query)` fusing `VectorRetriever` + `GraphRetriever` output while preserving provenance for each piece of evidence — returns a `HybridEvidence` dataclass (`vector_hits` with real filenames, `graph_hits` labeled `"knowledge graph"`, `graph_error` note); NO re-attribution or flattening — each evidence keeps its own provenance. Graph failure degrades to vector-only with a recorded error (app stays usable); vector failure propagates (no chunks = no evidence to answer with)
- [x] Wire `llamaindex_engine.py` to use `HybridRetriever` as the default retrieval strategy (configurable) — `LlamaIndexEngine(strategy="hybrid"|"vector")`, hybrid is the default; `_build_context` emits chunk blocks `[1]…[n]` + graph triplet blocks `[G1]…[Gn]` via the existing `GraphHit.to_text()`; `RetrievalResult` gained `graph_hits` (citations still vector-only — real filenames are VectorRetriever's job per Phase 9 decision)
- [x] Complete `tests/test_retrieval.py::test_hybrid_retrieval` end-to-end — asserts BOTH vector_hits and graph_hits non-empty for "How are remote work and information security related?", citations present, answer mentions remote/security/policy
- **Verify (DONE 2026-09-08):** hybrid test passes against real services: real chunks + real triplets fused in one prompt, answer grounded in both. Full suite **20/20 pass** (2m24s). Ponytail review: no new abstraction layers — HybridRetriever is ~20 lines composing the two existing retrievers; the "configurable" strategy is one constructor param ("hybrid"|"vector"), no env var needed until the UI wants a toggle (Phase 11's debug panel can pass strategy explicitly)

## Phase 11 — Streamlit UI
- [x] Implement `app/ui/sidebar.py`: document list, upload, process button, clear-knowledge-base (with confirmation dialog), system status panel (real health checks from `scripts/check_services.py` logic reused, not re-implemented)
- [x] Implement `app/ui/chat.py`: chat input/history, renders answer + sources block
- [x] Implement `app/ui/components.py`: shared widgets (status indicator, citation card, debug panel)
- [x] Implement `app/main.py`: wires everything, loads `Settings`, initializes managers once (cache via `st.session_state`/`st.cache_resource`), avoids reprocessing on every rerun
- [x] Implement developer/debug mode toggle (off by default) showing the §31 debug block (query, strategy, retrieved chunks/entities/relationships, final context, LLM response)
- [x] Implement file upload safety (§53): extension allowlist (`.pdf .docx .txt .md .html`), filename sanitization, no path traversal, save under `data/documents/` only
- [x] Implement friendly error messages for Ollama-down / Qdrant-down / model-missing (§33) — no raw stack traces in normal UI
- **Verify (DONE 2026-09-08):** streamlit 1.63.0 installed in `.venv`. Verified live in browser: sidebar lists all 11 docs; System Status shows 6 REAL green lines (Ollama 27 models, nomic-embed-text present, Ollama Cloud gpt-oss:120b responded, Qdrant 1.19.1, Cognee 2137 nodes/5340 relationships, Knowledge base 131 chunks) via reused `run_all_checks()` + new `cognee_status`/`knowledge_status` probes. End-to-end chat answered "10 working days of annual (paid) leave per year" with Sources `public_counsel_employee_handbook.pdf` + `pto-and-leave-policy.pdf` (evidence-derived, not LLM-derived). `RetrievalResult` gained `context` + `graph_error` fields so the §31 debug panel shows the final prompt context. Clear KB uses cognee 1.4.2's `forget(everything=True)` (verified signature) + `qdrant_manager.reset()` + metadata unlink, behind a popover confirmation. Upload safety: path-trip stripping + char allowlist + resolve-parent check. Ponytail review: no new abstractions — sidebar/chat/components are thin Streamlit renderers over the existing managers; engine cached per strategy in session state. BUG FIXED at root cause: `GraphRetriever._retrieve_async` imported cognee modules BEFORE `configure()`, so cognee's config cached site-packages storage paths → `sqlite3.OperationalError: unable to open database file` in fresh processes (the Phase 9 gotcha in a new disguise). Fix = reorder so `configure()` runs before any cognee import; full suite **20/20 pass** (2m34s).

## Phase 12 — Persistence & Reset
- [x] Confirm app does NOT rebuild the knowledge base on Streamlit restart — detects existing Qdrant collection (via `qdrant_manager.collection_exists`) + Cognee state and reuses it — engine builds lazily on first chat (main.py); nothing reprocesses on rerun/restart. Verified: fresh-process `scripts/ask_question.py` answered from the existing KB (graph 2137 nodes / 5340 relationships loaded, 5 vector hits + 5 triplets) with zero re-ingestion
- [x] Implement `scripts/reset_database.py`: calls `qdrant_manager.reset()` + clears Cognee dataset state + `data/metadata/` (with a `--yes` confirmation flag), preserves `data/documents/` unless `--purge-documents` explicitly passed — implemented as one shared `CognifyManager.reset()` = `cognee.forget(everything=True)` + drop ALL Qdrant collections (via new `qdrant_manager.list_collections()`); the script and the sidebar's Clear-KB button both route through it
- **Verify (DONE 2026-09-08):** REAL reset run: `forget(everything=True)` → `{'datasets_removed': 1, 'status': 'success'}`; after-state graph = "dataset 'main_dataset' not found (not ingested yet)" (the expected empty state) + **0 Qdrant collections** + both metadata JSONs unlinked + **11 source PDFs kept**. ROOT-CAUSE BUG FIXED in passing: the Phase 11 sidebar called `qdrant_manager.reset()`, which deletes `QDRANT_COLLECTION=enterprise_documents` — a collection Cognee's adapter never creates (real collections are `DocumentChunk_text`, `Entity_name`, `EdgeType_relationship_name`, …), so the old Clear-KB left every real vector behind. Verified against cognee 1.4.2 source + live probe: this graph is marked `delete_mode='graph_native'`/`provenance_version='1'` (matches `provenance/constants.py`), so `forget` routes the provenance path (`execute_source_ref_removal`) which deletes graph nodes AND vector points (2137 source refs found for the dataset); forget itself purged 5259 orphaned EdgeType nodes; only `EdgeType_relationship_name` remained → dropped by the belt-and-braces collection sweep. Post-reset full re-ingest (~20 min) restored 2137 nodes / 5340 relationships + all 6 collections. New `test_list_collections` passes; hermetic suites (config 9 + ingestion 2 + qdrant 3) green. WARNING: stop Streamlit before reset — Ladybug `.lbug` file lock (Windows error 33)

## Phase 13 — Automated Test Suite Completion
- [x] Fill remaining tests from instructions.md §46: `tests/test_health.py` (`test_ollama_connection`, `test_qdrant_connection`, `test_cognee_initialization` — mock only the truly-unavailable-in-CI parts), `tests/test_ingestion.py` remaining cases (`test_pdf_ingestion`, `test_txt_ingestion`)
- [x] Add the 4 Groundedness tests from §47 explicitly as a named test module if not already covered by Phase 8/10 tests
- **Verify (DONE 2026-09-08):** full suite **30/30 pass** (4m20s) against real services. `tests/test_health.py` (3 tests) REUSES `scripts/check_services.py` probes (no re-implementation); cloud-LLM leg SKIPS (never fails) when the paid endpoint is down per §46 "must not require paid cloud services"; `test_cognee_initialization` proves init by resolving Cognee's vector engine to `QDrantAdapter` (the community adapter only resolves after `configure()` registered it) + asserting storage redirected under PROJECT_ROOT. `test_pdf_ingestion`/`test_txt_ingestion` use real corpus bytes + Cognee's own extractor (`guess_file_type` + `extract_text_from_file`, verified against installed 1.4.2); txt compares against RAW bytes — `read_text` translates \r\n→\n on Windows and masks the extractor's true output. §47 module `tests/test_groundedness.py` (4 tests) with assertions grounded in the REAL corpus text (pto-and-leave-policy.pdf: 15 days at 0–2 yrs, 20 days at 3–5 yrs — verified by extracting the PDF, not guessed). ROOT-CAUSE FIX: unknown-question phrase check was brittle — LLM's perfectly-grounded "could not **be** found" didn't contain "not found" → shared `NOT_FOUND_PHRASES` in `tests/conftest.py`, used by both test_retrieval + test_groundedness (can't drift).

## Phase 14 — README & Final Documentation
- [x] Write `README.md` covering all 25 items in instructions.md §56 (architecture, why each tech, Windows setup, env vars, startup sequence incl. Ollama Cloud key setup, sample questions, debug mode, troubleshooting, limitations, future work) — no Docker instructions
- [x] In the env-var/setup section, show `OLLAMA_API_KEY=<your-ollama-api-key>` as a placeholder only — never a real key in README or any committed file
- [x] Finalize `requirements.txt` with versions actually installed/tested in `.venv` (not guessed) — DONE (2026-09-09): 12 direct deps pinned from `pip freeze` (cognee 1.4.2, cognee-community-vector-adapter-qdrant 0.4.0, llama-index 0.14.24 + 3 integration packs, qdrant-client 1.19.0, ollama 0.6.2, streamlit 1.63.0, python-dotenv, requests, pytest); `pip install -r requirements.txt` verified clean against the working `.venv`
- [x] Record chosen library versions (Cognee, LlamaIndex, Qdrant client, Streamlit) in README — done: §4 Technology Stack table lists real pip-list versions (Python 3.11.9, Cognee 1.4.2 + adapter 0.4.0, LlamaIndex 0.14.24 + integrations, Qdrant server 1.19.1 / client 1.19.0, Ollama client 0.6.2, Streamlit 1.63.0)
- **Verify (DONE 2026-09-09):** README.md written with all 25 §56 sections (script-checked: every heading string present); 3 "Docker" mentions are all "no Docker" statements, zero Docker setup instructions (§56 rule). Security grep: real `OLLAMA_API_KEY` value from `.env` occurs **0 times** across README/plan/instructions/requirements/.env.example — placeholder `<your-ollama-api-key>` only. Content grounded in real project state: verified service-check → ingest → `streamlit run app\main.py` startup order, real ledger/counts behavior (2,137 nodes / 5,340 relationships / 131 chunks), §21 troubleshooting rows all mirror observed Phase 5–12 gotchas (lbug lock, 408 saturation, 429 backoff, warm-embedding latency), tests-doc matches the 30-test suite incl. cloud-LLM skip. Full suite 30/30 pass remains green from Phase 13.

---

## Relevant Files
- `app/config/settings.py` — central `.env`-driven config, no hard-coded models/paths (Settings dataclass, validate() on from_env, paths resolved against project root)
- `tests/conftest.py` — puts project root on sys.path so `import app...` works from any CWD
- `app/llm/providers/base.py` — `LLMProvider` interface
- `app/llm/providers/local_ollama_provider.py` — `LocalOllamaProvider`
- `app/llm/providers/ollama_cloud_provider.py` — `OllamaCloudProvider` (isolates Ollama Cloud direct-API-key auth, native format, not OpenAI)
- `app/llm/ollama_manager.py` — thin factory selecting provider via `OLLAMA_PROVIDER` config
- `app/knowledge/cognee_manager.py` — sole owner of all Cognee calls; sole ingestion/embedding entry point
- `app/vectorstore/qdrant_manager.py` — thin operational layer only (health, collection info/existence, vector count, delete/reset) — never embeds or inserts
- `app/retrieval/vector_retriever.py`, `app/retrieval/graph_retriever.py`, `app/retrieval/hybrid_retriever.py` — retrieval abstractions per §24
- `app/retrieval/llamaindex_engine.py` — orchestration + grounded prompt (§25), provider-agnostic
- `app/ingestion/{document_manager,metadata}.py` — hashing, duplicate detection, metadata
- `app/ui/{sidebar,chat,components}.py`, `app/main.py` — Streamlit app
- `scripts/check_services.py`, `scripts/reset_database.py`
- `tests/test_*.py` — pytest suite per §46–47
- `.env.example` (placeholders only), `requirements.txt`, `README.md`

## Further Considerations
1. `llama-index-llms-ollama`'s `Ollama` class may not natively support a custom `host` pointed at `https://ollama.com` with a bearer token — `OllamaCloudProvider` includes a fallback to a `CustomLLM` subclass if the built-in class can't be configured this way. Verify against current package source before committing to either path.
2. Cognee's actual vector-backend adapter behavior (does it truly write LlamaIndex-compatible payloads into Qdrant?) is unknown until Phase 5 — the plan verifies this empirically on the 1–2 PDF subset (real graph nodes/relationships, real Qdrant collection/vector count/embedding dimension) rather than assuming compatibility or hard-coding a fixed "Cognee → Qdrant" pipeline shape.
3. Never commit a real API key anywhere outside `.env`; if one is ever accidentally exposed in any file or chat log, rotate it immediately at ollama.com/settings/keys.
