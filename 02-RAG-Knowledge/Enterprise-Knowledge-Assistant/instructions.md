# Enterprise Knowledge Assistant  ECoding Agent Instructions

## 1. Project Goal

Build a fully local, open-source **Enterprise Knowledge Assistant** for demonstrating:

- LlamaIndex
- Cognee
- Qdrant
- Ollama
- Streamlit
- Local document ingestion
- Vector retrieval
- Knowledge-graph/relationship retrieval
- Hybrid retrieval
- Grounded answers with citations

The application must allow a user to load enterprise documents and ask natural-language questions. Answers must be grounded in retrieved evidence and must show the supporting source documents.

The project is intended as a portfolio/demo application and should be technically clean, modular, reproducible, and easy to explain during a technical interview.

### Core principle

```text
Enterprise Documents
        ↁE     Cognee
        ↁEKnowledge extraction + graph construction
        ↁE      Qdrant
(vector storage / semantic retrieval)
        ↁE    LlamaIndex
(query orchestration / context handling)
        ↁE      Ollama
   (local LLM)
        ↁEGrounded Answer + Citations
        ↁE   Streamlit UI
```

Do not claim that a component performed work that it did not actually perform.

---

# 2. Current Project Environment

The current Windows project directory is:

```text
<project-root>
```

Use this directory as the project root unless the user explicitly changes it.

The project currently contains an `instructions.md` file and an external source repository:

```text
03LlamaIndex_RAGChatBot\
├── policy-rag-app\
└── ...
```

The source repository was cloned from:

```text
https://github.com/chindris-mihai-alexandru/policy-rag-app
```

Its `docs` directory contains the initial enterprise document corpus.

The project's own document directory must be:

```text
<project-root>\data\documents
```

The source repository is reference material only. Do not make the application dependent on the cloned repository at runtime.

---

# 3. Initial Document Corpus

The current corpus contains these 11 PDF files:

```text
acceptable-use-policy.pdf
benefits-overview.pdf
code-of-conduct.pdf
expense-reimbursement-policy.pdf
holiday-schedule.pdf
information-security-policy.pdf
onboarding-guide.pdf
performance-review-policy.pdf
pto-and-leave-policy.pdf
public_counsel_employee_handbook.pdf
remote-work-policy.pdf
```

They should be copied into:

```text
data\documents\
```

The application must treat them as normal user documents.

Do not hard-code answers from these documents.

Do not create fake relationships or fake metadata merely to make the demo look impressive.

---

# 4. Technology Stack

Use:

| Component | Technology | Responsibility |
|---|---|---|
| Language | Python 3.11+ | Application |
| RAG orchestration | LlamaIndex | Query orchestration, retrieval interfaces, context handling |
| Knowledge layer | Cognee | Document processing, entity/relationship extraction, knowledge graph |
| Vector database | Qdrant | Vector storage and semantic retrieval |
| LLM | Ollama | Local LLM inference |
| Embeddings | Ollama initially | Local embeddings |
| UI | Streamlit | Enterprise-style user interface |
| Configuration | python-dotenv / `.env` | Local configuration |
| Tests | pytest | Automated tests |

The application must be local-first.

---

# 5. Technologies Explicitly Excluded From V1

Do NOT use:

- OpenAI API
- Azure OpenAI
- Anthropic API
- Google Gemini API
- Paid cloud LLM APIs
- Pinecone Cloud
- Weaviate Cloud
- Cloud-hosted document processing
- Docker
- Docker Compose
- Kubernetes
- Ragas
- Multi-agent orchestration
- Agentic workflows
- Authentication/SSO
- Cloud deployment
- Fine-tuning
- Voice
- External enterprise connectors

Do not add technologies merely because a tutorial uses them.

If a dependency is required by Cognee or another selected library internally, distinguish between:
1. an application-level dependency we intentionally use, and
2. a transitive/internal dependency required by the library.

---

# 6. Important Current-Library Compatibility Rule

Library APIs change frequently.

Before implementing Cognee, LlamaIndex, Qdrant, or Ollama integrations:

1. Inspect the installed package version.
2. Check the current official documentation.
3. Check the installed package/API when documentation and examples disagree.
4. Use APIs supported by the installed version.
5. Do not copy old tutorials blindly.
6. Do not invent method names.
7. Keep vendor-specific code isolated.

Record the selected versions in:

```text
README.md
```

and, where appropriate:

```text
requirements.txt
```

### Cognee compatibility

Current Cognee documentation describes Cognee as a knowledge/memory layer that can ingest data, extract concepts and relationships, build a knowledge graph, and perform retrieval.

Cognee supports configurable:
- LLM providers
- embedding providers
- relational storage
- vector stores
- graph stores

Qdrant is available through a Cognee Qdrant adapter.

The implementation must therefore treat Cognee as the knowledge/graph layer rather than assuming that Cognee is merely a PDF parser.

### Important architecture rule

Do not blindly create two independent indexing pipelines that process the same document twice.

Prefer:

```text
Documents
   ↁECognee ingestion / knowledge construction
   ├── graph knowledge
   └── vector storage through configured Qdrant integration
             ↁE        LlamaIndex orchestration
             ↁE        retrieval/context
             ↁE           Ollama
```

If the selected library versions make direct sharing of a Qdrant collection unsafe, use clearly separated collections or a clean adapter layer.

Never assume that a Qdrant collection written by Cognee has exactly the same schema expected by a LlamaIndex `QdrantVectorStore`.

---

# 7. Architecture

## 7.1 Application Architecture

```text
                         USER
                           ━E                           ▼
                    ┌─────────────━E                    ━E Streamlit  ━E                    ━E    UI      ━E                    └──────┬──────━E                           ━E                           ▼
                    ┌─────────────━E                    ━ELlamaIndex  ━E                    ━EOrchestrator━E                    └──────┬──────━E                           ━E              ┌────────────┴────────────━E              ━E                        ━E              ▼                         ▼
        ┌───────────━E            ┌───────────━E        ━E Qdrant   ━E            ━E Cognee   ━E        ━E Vectors  ━E            ━E  Graph   ━E        └─────┬─────━E            └─────┬─────━E              ━E                        ━E              └──────────┬──────────────━E                         ▼
                 Retrieved Evidence
                         ━E                         ▼
                    ┌──────────━E                    ━E Ollama  ━E                    ━ELocal LLM━E                    └────┬─────━E                         ▼
                 Grounded Answer
                         ━E                         ▼
                   Source Citations
```

## 7.2 Responsibility Boundaries

### Streamlit

Responsible for:
- upload
- document list
- processing controls
- chat
- sources
- system status
- optional developer/debug view

### LlamaIndex

Responsible for:
- query orchestration
- retrieval abstraction
- context assembly
- response synthesis
- source/node handling
- local Ollama integration where appropriate

### Cognee

Responsible for:
- knowledge processing
- entity extraction
- relationship extraction
- knowledge graph construction
- graph-aware retrieval
- knowledge persistence

### Qdrant

Responsible for:
- vector storage
- semantic similarity search
- metadata/payload filtering

### Ollama

Responsible for:
- local LLM inference
- local embedding model, if configured as the embedding provider

---

# 8. Retrieval Strategy

Implement retrieval in stages.

## Stage 1  EVector Retrieval

```text
Question
   ↁEEmbedding
   ↁEQdrant
   ↁERelevant document chunks
```

## Stage 2  EGraph Retrieval

```text
Question
   ↁECognee
   ↁEEntities
   ↁERelationships
   ↁERelevant graph evidence
```

## Stage 3  EHybrid Retrieval

```text
                  Question
                     ━E              ┌──────┴──────━E              ▼             ▼
           Qdrant         Cognee
           vectors         graph
              ━E            ━E              └──────┬──────━E                     ▼
              Evidence fusion
                     ━E                     ▼
                LlamaIndex
                     ━E                     ▼
                  Ollama
```

The application-level hybrid layer should be implemented only after vector retrieval and graph retrieval work independently.

---

# 9. Cognee and Qdrant Storage Architecture

Cognee has multiple storage responsibilities.

Conceptually:

```text
Cognee
├── Relational/system metadata
├── Vector store
└── Graph store
```

For this project:

```text
Vector store ↁEQdrant
Graph store  ↁECognee-supported local graph backend
Metadata     ↁECognee-supported local persistence
```

Use a local graph backend supported by the installed Cognee version.

Do not introduce Neo4j unless:
- the installed Cognee version requires it, or
- there is a clear technical reason to demonstrate Neo4j.

For V1, keep infrastructure minimal.

---

# 10. Qdrant

Run Qdrant locally.

Recommended location:

```text
<project-root>\qdrant\
```

Example:

```text
qdrant\
├── qdrant.exe
└── storage\
```

Default endpoint:

```text
http://localhost:6333
```

Configuration:

```text
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=enterprise_documents
QDRANT_API_KEY=
```

If Cognee uses Qdrant directly, configure the Cognee Qdrant adapter according to the installed version.

Typical Cognee configuration concept:

```text
VECTOR_DB_PROVIDER=qdrant
VECTOR_DB_URL=http://localhost:6333
VECTOR_DB_KEY=
VECTOR_DATASET_DATABASE_HANDLER=qdrant
```

Do not assume these variables are identical across all Cognee versions. Verify the installed version.

### Vector dimensions

Never hard-code the vector dimension without verifying the embedding model.

The embedding model used during indexing and querying must be compatible.

If the embedding model changes:
- do not reuse an incompatible collection;
- rebuild/recreate the relevant collection as required.

This prevents errors such as:

```text
Vector dimension mismatch
```

---

# 11. Ollama

Ollama runs locally.

Default endpoint:

```text
http://localhost:11434
```

Initial recommended configuration:

```text
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=qwen3:8b
OLLAMA_EMBED_MODEL=nomic-embed-text
```

These are configuration examples, not mandatory models.

The application must read model names from `.env`.

At startup, check:

1. Ollama connectivity
2. LLM model availability
3. embedding model availability

Example:

```powershell
ollama list
```

If the configured model is missing, show an actionable error.

Do not automatically download large models without explicit user action.

---

# 12. Embeddings

Use a local embedding model.

Initial choice:

```text
nomic-embed-text
```

But keep it configurable.

Requirements:

- same embedding model for indexing and query embeddings
- same vector dimension
- explicit rebuild mechanism when embedding configuration changes
- no cloud embedding API

Store embedding configuration in metadata/configuration so a future operator can determine how a collection was created.

---

# 13. Supported Documents

V1 must support:

- PDF
- DOCX
- TXT
- Markdown
- HTML

The first working corpus is PDF.

Design the ingestion layer so additional formats can be added without rewriting the retrieval system.

---

# 14. Document Directory

Use:

```text
data\
├── documents\
└── metadata\
```

The current PDF corpus belongs in:

```text
data\documents\
```

Do not make the application depend on:

```text
policy-rag-app\docs\
```

The cloned repository is only a source/reference repository.

---

# 15. Document Metadata

Track, where available:

```text
document_id
filename
document_type
department
version
upload_date
source_path
file_hash
status
```

For example:

```text
filename       = pto-and-leave-policy.pdf
document_type  = Policy
department     = HR
version        = Unknown
upload_date    = 2026-09-06
source_path    = data/documents/pto-and-leave-policy.pdf
```

Do not invent a document version if the source document does not contain one.

Use:

```text
Unknown
```

or null where appropriate.

---

# 16. Duplicate Detection

Calculate a deterministic file hash such as SHA-256.

When a document is uploaded:

```text
File
 ↁESHA-256
 ↁECompare existing metadata
```

If the same file already exists:

```text
Document already indexed.
```

Do not create duplicate vectors or duplicate graph records.

If the file content changes:
- detect the changed hash;
- provide a controlled re-index operation.

---

# 17. Document Processing

The UI should support:

```text
Upload Documents

[ Select Files ]

[ Process Documents ]
```

Processing should report actual values:

```text
Documents processed: 11
Chunks created: <actual>
Entities extracted: <actual>
Relationships extracted: <actual>
Status: Completed
```

Never fabricate counts.

If a library does not expose a count reliably, display:

```text
Not available
```

rather than inventing a number.

---

# 18. Chunking

Chunking must preserve useful context.

Make these configurable:

```text
CHUNK_SIZE
CHUNK_OVERLAP
```

Start with reasonable values and verify retrieval quality rather than treating a specific number as universally correct.

Example configuration:

```text
CHUNK_SIZE=800
CHUNK_OVERLAP=100
```

The actual implementation may use a LlamaIndex/Cognee-native chunking strategy if that is better supported.

Document the chosen strategy.

---

# 19. Qdrant Payload

Where the selected Qdrant integration supports it, preserve useful metadata:

```text
document_id
chunk_id
filename
page
document_type
department
version
upload_date
source_path
file_hash
```

Use metadata/payload filters where appropriate.

Do not store unnecessary duplicate copies of full documents inside Qdrant.

---

# 20. Knowledge Graph

Knowledge graph content must come from actual document evidence.

Example:

```text
Employee
   ━E   └── follows ↁELeave Policy
                      ━E                      ├── allows ↁEAnnual Leave
                      └── requires ↁEManager Approval
```

Another example:

```text
Expense
   ━E   └── governed_by ↁEExpense Policy
```

These are examples of possible relationships only.

Do not hard-code these relationships.

The application must derive them from actual document content through Cognee.

---

# 21. Graph Querying

Implement a graph retriever abstraction:

```python
class GraphRetriever:
    def retrieve(self, query: str):
        ...
```

The implementation must call the supported Cognee APIs for the installed version.

Do not assume legacy API names.

Keep Cognee-specific code in:

```text
app\knowledge\cognee_manager.py
```

or a small number of clearly defined Cognee modules.

Do not scatter Cognee calls throughout the application.

---

# 22. LlamaIndex

Use LlamaIndex as the application's RAG/query orchestration layer.

Recommended responsibilities:

- query handling
- retriever abstraction
- context assembly
- response synthesis
- source/node handling
- local Ollama LLM integration
- optional Qdrant vector-store integration where schema ownership is clear

Relevant packages should be installed only when needed.

Likely packages include:

```text
llama-index
llama-index-llms-ollama
llama-index-embeddings-ollama
llama-index-vector-stores-qdrant
qdrant-client
```

Verify package names and compatibility before finalizing `requirements.txt`.

---

# 23. Important Qdrant/LlamaIndex Integration Rule

LlamaIndex has a Qdrant vector-store integration.

However, do not assume that:

```text
Cognee writes Qdrant collection
```

and

```text
LlamaIndex reads the same collection
```

will automatically be compatible.

First inspect the actual collection schema and the selected library APIs.

If direct sharing is compatible, use it.

If not, choose one of these clean designs:

### Design A  ECognee-owned Qdrant

```text
Documents
   ↁECognee
   ↁEQdrant + Graph
   ↁECognee retrieval
   ↁELlamaIndex orchestration
```

### Design B  ESeparate collections

```text
Cognee
   ↁEQdrant collection: cognee_*

LlamaIndex
   ↁEQdrant collection: llamaindex_*
```

Use this only if there is a technical reason.

### Design C  EAdapter layer

```text
LlamaIndex Retriever
        ↁEApplication adapter
        ↁECognee retrieval
```

This is acceptable when direct Qdrant schema sharing is unsafe.

Choose the simplest design that is reliable and explainable.

---

# 24. Retrieval Abstractions

Implement:

```text
Retriever
├── VectorRetriever
├── GraphRetriever
└── HybridRetriever
```

### VectorRetriever

Returns:

```text
document
chunk
score
metadata
source
```

### GraphRetriever

Returns:

```text
entities
relationships
supporting evidence
source metadata
```

### HybridRetriever

Combines both.

The hybrid result must preserve provenance.

---

# 25. Grounded LLM Prompt

The local LLM must be instructed:

```text
Answer the user's question using only the provided enterprise
knowledge context.

If the context does not contain enough information to answer,
say that the information could not be found in the available
documents.

Do not invent facts, policies, numbers, dates, sources, or page
numbers.

Preserve exact numbers and dates from the evidence.

When multiple documents provide evidence, distinguish them clearly.

Provide source citations for claims supported by retrieved evidence.
```

The application must not allow the model to fabricate citations.

---

# 26. Unknown Questions

This is a mandatory feature.

For example:

```text
User:
What is the company's private jet travel policy?
```

If the corpus contains no answer, respond with something like:

```text
I could not find information about private jet travel
in the available enterprise documents.
```

Do not generate a plausible policy.

This should be tested automatically.

---

# 27. Citations

Every answer should expose available source information.

Example:

```text
Answer:

Employees can carry forward unused leave according to the policy.

Sources:
📄 pto-and-leave-policy.pdf
```

If page information is reliably available:

```text
📄 pto-and-leave-policy.pdf  EPage 4
```

Never fabricate page numbers.

If the PDF parser does not provide reliable page metadata, omit the page.

The citation should originate from retrieved metadata, not from the LLM's imagination.

---

# 28. Multi-Document Questions

The application should support questions that require evidence from multiple documents.

Examples:

```text
What security requirements apply to employees working remotely?
```

```text
What expenses require manager approval?
```

```text
How do the employee handbook and leave policy relate?
```

The answer should identify the relevant documents.

---

# 29. Version Comparison

The architecture should support multiple versions.

Example:

```text
Leave Policy
├── 2025
└── 2026
```

However, the current downloaded corpus may not contain multiple versions of every policy.

Do not pretend it does.

If a question asks:

```text
What changed between the 2025 and 2026 leave policies?
```

and only one version exists, the system must say that both versions were not found.

---

# 30. Streamlit UI

Create an enterprise-style interface.

Recommended sections:

```text
Enterprise Knowledge Assistant

Sidebar
---------
Documents
Upload
Process
Document List
Clear Knowledge Base

System Status
-------------
Ollama
Qdrant
Cognee

Configuration
-------------
LLM
Embedding
Top K

Main Area
---------
Chat
Sources
```

Do not expose unnecessary implementation details to normal users.

---

# 31. Developer / Debug Mode

Provide an optional developer mode.

When enabled, show:

```text
Query
Retrieval Strategy
Retrieved Documents
Retrieved Chunks
Scores
Metadata
Graph Entities
Graph Relationships
Final Context
LLM Response
```

This mode is important for the portfolio demo because it makes the architecture observable.

Do not expose it by default.

Do not display entire confidential documents unnecessarily.

---

# 32. System Health

Display:

```text
Ollama      ◁EConnected
Qdrant      ◁EConnected
Cognee      ◁EReady
Knowledge   ◁EIndexed
```

Health checks must be real.

Do not display `Connected` merely because configuration exists.

---

# 33. Error Handling

Never expose raw stack traces in the normal UI.

Use useful messages:

```text
Ollama is not running.

Please start Ollama and try again.
```

```text
Qdrant is unavailable.

Please verify that Qdrant is running on
http://localhost:6333.
```

```text
The configured embedding model is unavailable.

Please install the model in Ollama or change the configuration.
```

Detailed exceptions may be written to developer logs.

---

# 34. Logging

Use application logging.

Log events such as:

```text
Application started
Ollama health check
Qdrant health check
Cognee initialized
Document uploaded
Document hash calculated
Document processing started
Document processing completed
Knowledge graph updated
Vector index updated
User query received
Retrieval started
Retrieval completed
LLM generation started
LLM generation completed
Errors
```

Never log:

- passwords
- API keys
- authentication tokens
- full confidential documents
- unnecessary document contents

---

# 35. Persistence

The following must survive application restart:

```text
Uploaded documents
Document metadata
Qdrant vectors
Cognee knowledge
Cognee metadata/state
```

Do not rebuild the complete knowledge base whenever Streamlit starts.

At startup:

```text
Detect existing state
        ↁEReuse it
```

Only process documents when explicitly requested or when a controlled update is required.

---

# 36. Clear / Reset Knowledge Base

Provide a developer/admin action:

```text
Clear Knowledge Base
```

This must:

- remove indexed vectors
- remove Cognee knowledge associated with the application dataset
- remove document metadata if appropriate
- preserve original source documents unless the user explicitly chooses to delete them

Ask for confirmation before destructive operations.

---

# 37. Project Structure

Use this structure:

```text
03LlamaIndex_RAGChatBot/
━E├── README.md
├── instructions.md
├── requirements.txt
├── .env.example
├── .gitignore
━E├── app/
━E  ├── main.py
━E  ━E━E  ├── config/
━E  ━E  └── settings.py
━E  ━E━E  ├── ui/
━E  ━E  ├── chat.py
━E  ━E  ├── sidebar.py
━E  ━E  └── components.py
━E  ━E━E  ├── ingestion/
━E  ━E  ├── document_ingestion.py
━E  ━E  ├── document_manager.py
━E  ━E  └── metadata.py
━E  ━E━E  ├── retrieval/
━E  ━E  ├── llamaindex_engine.py
━E  ━E  ├── vector_retriever.py
━E  ━E  ├── graph_retriever.py
━E  ━E  └── hybrid_retriever.py
━E  ━E━E  ├── knowledge/
━E  ━E  └── cognee_manager.py
━E  ━E━E  ├── vectorstore/
━E  ━E  └── qdrant_manager.py
━E  ━E━E  ├── llm/
━E  ━E  └── ollama_manager.py
━E  ━E━E  └── models/
━E      └── schemas.py
━E├── data/
━E  ├── documents/
━E  └── metadata/
━E├── logs/
━E├── tests/
━E  ├── test_configuration.py
━E  ├── test_health.py
━E  ├── test_ingestion.py
━E  ├── test_qdrant.py
━E  └── test_retrieval.py
━E├── scripts/
━E  ├── check_services.py
━E  └── reset_database.py
━E└── policy-rag-app/
    └── docs/
```

The `policy-rag-app` directory is source/reference data and must not be imported as an application module.

---

# 38. Configuration

Create:

```text
.env.example
```

Initial example:

```text
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=qwen3:8b
OLLAMA_EMBED_MODEL=nomic-embed-text

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=enterprise_documents
QDRANT_API_KEY=

TOP_K=5
CHUNK_SIZE=800
CHUNK_OVERLAP=100

DATA_DIR=./data
DOCUMENT_DIR=./data/documents
METADATA_DIR=./data/metadata

LOG_LEVEL=INFO
```

If Cognee requires additional variables, add them after verifying the installed version.

Never commit `.env`.

---

# 39. Windows Environment

The target environment is:

```text
Windows 11
PowerShell
Python 3.11+
Local virtual environment
Ollama native
Qdrant native
```

Do not require Linux shell commands.

Do not require WSL.

Do not require Docker.

---

# 40. Python Virtual Environment

Use a project-specific virtual environment.

From the project root:

```powershell
python -m venv .venv
```

Activate:

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Do not require global package installation.

---

# 41. Dependency Management

Before finalizing `requirements.txt`:

1. Check the installed Python version.
2. Check the current Cognee version.
3. Check the current LlamaIndex version.
4. Check Qdrant client version.
5. Check Ollama integration packages.
6. Check Streamlit.
7. Resolve compatibility.
8. Test installation in the project's `.venv`.

Prefer compatible pinned or minimum versions based on the tested environment.

Do not blindly use versions from old blog posts.

---

# 42. Qdrant Startup

Expected native startup:

```powershell
cd <project-root>\qdrant
.\qdrant.exe
```

Verify:

```text
http://localhost:6333
```

The exact persistent-storage configuration must match the selected Qdrant version.

Do not require Docker.

---

# 43. Ollama Startup

Verify:

```powershell
ollama list
```

The application must not assume that the selected models are installed.

If necessary:

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

Only perform downloads when the user explicitly chooses to install the models.

---

# 44. Application Startup

Typical workflow:

### Terminal 1

```powershell
cd <project-root>\qdrant
.\qdrant.exe
```

### Terminal 2

```powershell
ollama list
```

### Terminal 3

```powershell
cd <project-root>
.\.venv\Scripts\Activate.ps1
streamlit run app\main.py
```

Document the actual Streamlit URL in README after running it.

---

# 45. Development Phases

Do NOT build the whole system in one step.

## Phase 1  EEnvironment

Verify:

```text
Python
Virtual environment
Ollama
Qdrant
```

Create a health-check script.

---

## Phase 2  EDocument Inventory

Verify the 11 PDF files in:

```text
data\documents\
```

Build document metadata.

Calculate file hashes.

---

## Phase 3  EBasic Cognee Ingestion

Implement:

```text
Document
   ↁECognee
   ↁEKnowledge
```

Verify that Cognee successfully processes a small subset first.

Do not process all 11 files until one or two files work.

---

## Phase 4  EQdrant

Configure Qdrant.

Verify:

```text
Embedding
   ↁEQdrant
   ↁESimilarity search
```

Confirm vector dimension.

---

## Phase 5  ELlamaIndex

Implement basic query orchestration:

```text
Question
   ↁELlamaIndex
   ↁERetriever
   ↁEContext
   ↁEOllama
   ↁEAnswer
```

Verify basic RAG before adding graph retrieval.

---

## Phase 6  ECitations

Add:

```text
Answer
+
Filename
+
Page when reliable
+
Metadata
```

Verify citations are derived from actual retrieved nodes.

---

## Phase 7  EGraph Retrieval

Add Cognee graph retrieval.

Verify entity and relationship queries.

Example:

```text
Which policy governs remote work?
```

---

## Phase 8  EHybrid Retrieval

Combine:

```text
Vector evidence
+
Graph evidence
```

Use LlamaIndex/application orchestration to create the final context.

---

## Phase 9  EStreamlit

Add:

```text
Upload
Process
Documents
Chat
Sources
Status
Debug mode
```

---

## Phase 10  ETesting

Add pytest tests.

---

## Phase 11  EREADME

Document:

- architecture
- setup
- configuration
- startup
- document processing
- sample questions
- troubleshooting
- project structure
- limitations
- future enhancements

---

# 46. Testing

Use pytest.

## Configuration tests

```text
test_configuration_loading
test_default_configuration
```

## Health tests

```text
test_ollama_connection
test_qdrant_connection
test_cognee_initialization
```

Use mocks where external services are not available.

## Ingestion tests

```text
test_pdf_ingestion
test_txt_ingestion
test_metadata_creation
test_duplicate_detection
```

## Qdrant tests

```text
test_collection
test_vector_insertion
test_vector_retrieval
```

## Retrieval tests

```text
test_relevant_question
test_no_relevant_information
test_source_metadata
test_hybrid_retrieval
```

Tests must not require paid cloud services.

---

# 47. Groundedness Tests

At minimum, test:

### Known question

```text
How many annual leave days do employees receive?
```

Expected:

- relevant answer
- source citation
- no invented information

### Unknown question

```text
What is the company's private jet travel policy?
```

Expected:

- explicit "not found" response
- no fabricated policy
- no fabricated citation

### Source test

Verify that the filename shown in the answer exists in the indexed corpus.

### Page test

If a page number is displayed, verify that it came from source metadata.

---

# 48. Demo Questions

Use questions based on the actual corpus.

Good examples:

```text
What does the acceptable use policy cover?
```

```text
What are the employee benefits described in the documents?
```

```text
What expenses require approval?
```

```text
What security requirements apply to employees?
```

```text
What are the rules for remote work?
```

```text
What is covered by the employee code of conduct?
```

```text
What is the onboarding process?
```

```text
What is the performance review process?
```

```text
What holidays are listed in the holiday schedule?
```

```text
What is the relationship between remote work and information security?
```

```text
What is the company's private jet travel policy?
```

The final question should demonstrate hallucination resistance.

Do not use questions that assume facts not present in the corpus.

---

# 49. Portfolio Demonstration

The technical demo should show:

## Demo 1  EDocument ingestion

```text
Upload PDF
   ↁEProcess
   ↁECognee
   ↁEEntities + relationships
   ↁEQdrant vectors
```

## Demo 2  ENormal RAG

Ask:

```text
What is the remote work policy?
```

Show:

```text
Answer
Sources
```

## Demo 3  EMulti-document retrieval

Ask a question requiring information from multiple policies.

Show multiple sources.

## Demo 4  EGraph reasoning

Ask:

```text
How are remote work and information security related?
```

Show:

```text
Vector Evidence
+
Graph Evidence
```

## Demo 5  EHallucination resistance

Ask:

```text
What is the private jet travel policy?
```

Show:

```text
Information not found.
```

This is an important portfolio feature.

---

# 50. Debug Mode

When developer mode is enabled, display:

```text
Query
────────────────────────
<user question>

Retrieval Strategy
────────────────────────
Hybrid

Vector Results
────────────────────────
1. document.pdf
2. document.pdf

Graph Entities
────────────────────────
Entity A
Entity B

Graph Relationships
────────────────────────
Entity A ──relationship──> Entity B

Evidence
────────────────────────
<retrieved evidence>

Sources
────────────────────────
<citations>

Final Prompt Context
────────────────────────
<sanitized context>

LLM Response
────────────────────────
<answer>
```

Do not expose secrets.

---

# 51. Performance

V1 prioritizes:

1. correctness
2. explainability
3. maintainability
4. reproducibility

Then optimize performance.

Avoid:

- reprocessing unchanged documents
- duplicate embeddings
- unnecessary LLM calls
- excessive context
- rebuilding the entire knowledge base on startup

Keep:

```text
TOP_K
```

configurable.

---

# 52. Security

The application is local-only by default.

Requirements:

- do not expose services publicly
- do not send documents to cloud AI services
- do not hard-code credentials
- do not log secrets
- do not expose authentication tokens
- do not expose unnecessary document contents
- validate uploaded files
- restrict supported file types
- avoid path traversal when handling uploads

Authentication is out of scope for V1.

---

# 53. File Upload Safety

Accept only:

```text
.pdf
.docx
.txt
.md
.html
```

Reject unsupported extensions.

Store uploaded files under the application document directory.

Never trust the original filename as a filesystem path.

Sanitize filenames.

Do not allow uploaded content to overwrite:

```text
.env
requirements.txt
application code
configuration files
```

---

# 54. Scope Boundaries

V1 is:

```text
Local Enterprise Document Knowledge Assistant
```

V1 is NOT:

```text
Agentic system
Multi-agent system
Evaluation platform
Enterprise SSO platform
Cloud service
```

Keep the implementation focused.

---

# 55. Future Extensions

After V1 works:

```text
V1
Local Enterprise Knowledge Assistant
        ↁEV2
Advanced Vector + Graph Hybrid Retrieval
        ↁEV3
RAG Evaluation
        ↁEV4
Agentic RAG
        ↁEV5
Multi-Agent Enterprise Assistant
```

Possible future features:

- Ragas
- LLM-as-judge evaluation
- retrieval evaluation
- reranking
- document version comparison
- enterprise authentication
- SQL tools
- REST APIs
- GitHub
- SharePoint
- Confluence
- MCP
- advanced graph visualization
- observability

Do not implement these in V1.

---

# 56. README Requirements

README.md must contain:

1. Project overview
2. Business/use-case explanation
3. Architecture diagram
4. Technology stack
5. Why Cognee
6. Why Qdrant
7. Why LlamaIndex
8. Why Ollama
9. Prerequisites
10. Windows setup
11. Virtual environment setup
12. Ollama setup
13. Qdrant setup
14. Cognee configuration
15. Environment variables
16. Dependency installation
17. Document ingestion
18. Application startup
19. Sample questions
20. Debug mode
21. Troubleshooting
22. Testing
23. Project structure
24. Limitations
25. Future enhancements

README must not contain Docker instructions for the V1 setup.

---

# 57. Development Rules

After every implementation phase:

1. Run the application or relevant component.
2. Verify the previous phase still works.
3. Run relevant tests.
4. Fix errors.
5. Only then continue.

Do not create large amounts of untested code.

Do not replace working components unnecessarily.

Do not rewrite the project architecture because of a minor library API issue.

Instead:
- isolate the API-specific code;
- adapt the integration layer;
- preserve the application's interfaces.

---

# 58. Coding Style

Use:

- type hints
- docstrings for important public functions
- small functions
- clear names
- modular classes
- structured logging
- configuration objects
- exception handling
- deterministic file hashing

Avoid:

- global mutable state
- hard-coded paths
- hard-coded model names
- hard-coded vector dimensions
- giant single-file applications
- duplicated Cognee calls
- duplicated Qdrant logic
- hidden cloud dependencies

---

# 59. Definition of Done

The V1 application is complete when the following work locally:

```text
✁EWindows native setup
✁EPython virtual environment
✁EOllama running locally
✁EQdrant running locally
✁ENo Docker dependency
✁EPDF ingestion
✁EDOCX ingestion
✁ETXT ingestion
✁EMarkdown ingestion
✁EHTML ingestion
✁EDocument metadata
✁EDuplicate detection
✁ECognee knowledge processing
✁EKnowledge graph creation
✁ELocal embedding generation
✁EQdrant vector storage
✁ELlamaIndex query orchestration
✁ELocal Ollama LLM
✁EGrounded answers
✁ESource citations
✁EUnknown-question handling
✁EPersistent data
✁EDocument management
✁EHealth checks
✁ELogging
✁EError handling
✁EBasic automated tests
✁EDeveloper/debug mode
✁EREADME
✁EClean modular architecture
```

---

# 60. Final Architecture Principle

Maintain a clean separation:

```text
                         USER
                           ━E                           ▼
                      Streamlit
                           ━E                           ▼
                     LlamaIndex
                   Query Orchestrator
                           ━E              ┌────────────┴────────────━E              ━E                        ━E              ▼                         ▼
           Qdrant                    Cognee
       Vector Evidence          Graph Evidence
              ━E                        ━E              └────────────┬────────────━E                           ▼
                    Evidence Fusion
                           ━E                           ▼
                         Ollama
                       Local LLM
                           ━E                           ▼
                   Grounded Answer
                           ━E                           ▼
                    Source Citations
```

The most important rule is:

> **Never fabricate evidence, relationships, source names, page numbers, metadata, processing counts, or answers.**

The application must demonstrate that the system can retrieve information from enterprise documents, reason over relationships when appropriate, and clearly say when the information is not present.

## Portfolio positioning

The project should be explainable in one sentence:

> **A fully local enterprise knowledge assistant that combines Cognee's knowledge graph, Qdrant vector search, LlamaIndex retrieval orchestration, and Ollama local LLM inference to provide grounded, citation-backed answers from enterprise documents.**

