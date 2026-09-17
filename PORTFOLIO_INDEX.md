# PORTFOLIO_INDEX.md — AI / ML Portfolio Index

## Portfolio Overview

This portfolio demonstrates practical AI engineering across:

1. **Agentic AI & Multi-Agent Systems** — dynamic workflow orchestration, tool protocols, hierarchical agents, stateful business agents
2. **RAG & Knowledge Engineering** — hybrid retrieval, graph RAG, knowledge-base generation, RAG evaluation
3. **AI Safety & Quality Engineering** — guardrails, injection defense, PII protection, LLM-as-a-judge
4. **Applied AI** — document intelligence, voice pipelines
5. **NLP & Machine Learning** — classical supervised NLP

Technology coverage was verified against the projects' code and requirements files; items not verifiable in the repository are marked `To be verified`.

---

# 1. Agentic AI & Multi-Agent Systems

## 1. AgentFlow — Dynamic Multi-Agent Workflow & Skill Orchestrator

**Folder:** [`01-Agentic-AI/AgentFlow-Orchestrator/`](./01-Agentic-AI/AgentFlow-Orchestrator/)

**Purpose:** A dynamic multi-agent orchestration platform where an LLM converts user intent into a structured agent workflow, obtains approval, executes the workflow through tools, evaluates the result and can save successful workflows as reusable skills.

**Focus:** Dynamic agent planning and workflow orchestration

**Technologies:** Google ADK · FastAPI · React

**Demonstrates:**
- LLM workflow planning
- structured agent plans
- DAG orchestration
- user approval gate
- evaluator stage
- reusable skills

**How it differs:** Dynamic workflow generation rather than a fixed multi-agent hierarchy.

---

## 2. Agentic AI MCP Tool Orchestration Platform

**Folder:** [`01-Agentic-AI/MCP-Tool-Orchestration/`](./01-Agentic-AI/MCP-Tool-Orchestration/)

**Purpose:** An agentic AI tool-orchestration platform demonstrating how an LLM can interact with a collection of MCP tool servers through a controlled tool-calling workflow.

**Focus:** Model Context Protocol tool ecosystem and multi-tool orchestration

**Technologies:** MCP · Agno · Streamlit · Ollama Cloud

**Demonstrates:**
- MCP tool discovery
- multi-tool orchestration over stdio
- tool calling with retries
- tool execution control

**How it differs:** MCP-based tool ecosystem and tool orchestration — not a multi-agent hierarchy and not a chatbot.

---

## 3. Agentic AI E-Commerce Multi-Agent Orchestrator

**Folder:** [`01-Agentic-AI/MultiAgent-Ecommerce/`](./01-Agentic-AI/MultiAgent-Ecommerce/)

**Purpose:** A fixed hierarchical multi-agent system where an orchestrator delegates domain tasks to specialized catalog, checkout and order-summary agents.

**Focus:** Hierarchical multi-agent architecture with specialized domain agents

**Technologies:** Google ADK · LiteLLM · Ollama Cloud · ADK Dev UI

**Architecture:**
```text
User → Orchestrator Agent
         ├── Catalog Agent
         ├── Checkout Agent
         └── Order Summary Agent
```

**How it differs:** Fixed hierarchical multi-agent architecture — compared with AgentFlow's dynamic workflow generation.

---

## 4. Agentic Order Returns & Fraud Prevention Agent

**Folder:** [`01-Agentic-AI/OrderReturns-Fraud-Agent/`](./01-Agentic-AI/OrderReturns-Fraud-Agent/)

**Purpose:** A stateful business-process agent where AI interprets the request but deterministic code makes policy/refund decisions, with human approval for high-risk cases.

**Focus:** Stateful agentic workflow with deterministic policy enforcement

**Technologies:** LangGraph · FastAPI · Streamlit · SQLite checkpointing · Ollama Cloud

**Demonstrates:**
- return reason classification
- deterministic business rules (30-day window, return fees)
- photo-proof handling
- fraud scoring
- manager approval (human-in-the-loop)
- SQLite checkpointing

**How it differs:** Stateful business workflow + HITL — AI interprets, code decides.

---

## 5. AI Hospital Appointment Scheduler & Confirmation Agent

**Folder:** [`01-Agentic-AI/Hospital-Appointment-Agent/`](./01-Agentic-AI/Hospital-Appointment-Agent/)

**Purpose:** Converts free-form natural-language appointment requests into validated appointments through LLM structured extraction followed by deterministic calendar rules and SMS confirmation.

**Focus:** LLM structured extraction + deterministic business rules

**Technologies:** LangChain LCEL · FastAPI · SQLite · Twilio SMS · Ollama Cloud

**Architecture:**
```text
Natural Language Request → LLM Structured Extraction → Validated Data
→ Deterministic Calendar Rules → Appointment → SMS Confirmation
```

**How it differs:** LLM extracts intent/data while deterministic Python controls appointment decisions.

---

## 6. Agentic AI Multi-Agent Mindmap Orchestrator

**Folder:** [`01-Agentic-AI/MultiAgent-Mindmap/`](./01-Agentic-AI/MultiAgent-Mindmap/)

**Purpose:** A multi-agent mindmap generation and review workflow demonstrating iterative agent-based refinement of structured knowledge. *(Positioning subject to verification — the detailed user guide was unavailable during portfolio analysis.)*

**Focus:** Iterative multi-agent review/refinement

**Technologies:** Streamlit · Ollama · markmap.js

**How it differs:** 3-agent iterative review loop for knowledge refinement.

---

# 2. RAG & Knowledge Engineering

## 7. Production RAG Documentation Assistant

**Folder:** [`02-RAG-Knowledge/Production-RAG/`](./02-RAG-Knowledge/Production-RAG/)

**Purpose:** A production-oriented RAG system focused on retrieval engineering — chunking, hybrid retrieval, fusion, citations, refusal behavior and regression evaluation.

**Focus:** Retrieval engineering + production-style RAG evaluation

**Technologies:** LangGraph · ChromaDB · BM25 · FastAPI · Ollama Cloud · nomic-embed-text

**Demonstrates:**
- semantic chunking
- hybrid retrieval (BM25 + vector)
- Reciprocal Rank Fusion
- grounded generation with citations
- refusal behavior
- frozen golden question set evaluation (recall@k, citation coverage, refusal accuracy)

**How it differs:** Retrieval engineering and regression evaluation rather than a chat UI.

---

## 8. Enterprise Knowledge Assistant — Hybrid Graph RAG

**Folder:** [`02-RAG-Knowledge/Enterprise-Knowledge-Assistant/`](./02-RAG-Knowledge/Enterprise-Knowledge-Assistant/)

**Purpose:** Enterprise document RAG combining vector, lexical (BM25) and knowledge-graph retrieval with RRF fusion and an evidence gate before generation.

**Focus:** Hybrid vector + lexical + graph retrieval

**Technologies:** LlamaIndex · Cognee · Qdrant · BM25 · Ollama · nomic-embed-text

**Architecture:**
```text
Documents → Vector Retrieval + BM25 + Knowledge Graph → RRF Fusion
→ Evidence Gate → LLM → Cited Answer / Refusal
```

**How it differs:** Three retrieval modes fused with an evidence gate for enterprise knowledge.

---

## 9. RAG Evaluation & LLM Quality Engineering Harness

**Folder:** [`02-RAG-Knowledge/RAG-Evaluation-Harness/`](./02-RAG-Knowledge/RAG-Evaluation-Harness/)

**Purpose:** An evaluation harness that measures RAG/LLM system quality — LLM-as-a-judge metrics, regression testing and automated comparison — rather than being another RAG application.

**Focus:** AI/RAG quality measurement and regression testing

**Technologies:** RAGAS · Streamlit · pytest · OpenAI-compatible judge LLMs

**Demonstrates:**
- context relevance / precision / recall
- groundedness & faithfulness
- factual correctness, similarity
- automated comparison & regression testing

**How it differs:** Evaluates AI systems instead of building them.

---

## 10. LLM Wiki — AI Knowledge Base Generator

**Folder:** [`02-RAG-Knowledge/LLM-Wiki/`](./02-RAG-Knowledge/LLM-Wiki/)

**Purpose:** Converts documents into a navigable, Git-friendly markdown knowledge base with source/entity/concept pages, wiki links and graph visualization.

**Focus:** Document-to-knowledge-base transformation

**Technologies:** FastAPI · React 18 · Vite · Zustand · D3 · Markdown + YAML frontmatter · llama-cpp-python (local GGUF) · OpenAI/Azure/Anthropic/Ollama/LM Studio/Together/Baseten SDKs

**Verified capabilities** (from code + the shipped user guide): 8 LLM providers including keyless local GGUF models served in-process; `===FILE:===` ingest contract with `AGENTS.md` schema-in-Markdown; grounded wiki-only query mode with citation chips and confidence score (SSE streaming); two-phase health check (programmatic link lint + LLM narrative review); path-traversal guards and append-only activity log.

**Architecture:**
```text
Documents → LLM Knowledge Extraction → Source/Entity/Concept Pages
→ Markdown Knowledge Base → Wiki Links → Graph Visualization
```

**How it differs:** Produces a persistent navigable knowledge base rather than only answering questions.

---

## 11. AI Knowledge Graph Builder & Graph RAG Explorer

**Folder:** [`02-RAG-Knowledge/Knowledge-Graph-Builder/`](./02-RAG-Knowledge/Knowledge-Graph-Builder/)

**Purpose:** Graph-native knowledge construction and querying — schema refinement via an agent loop, deterministic Cypher generation and a streaming query interface over Neo4j.

**Focus:** Knowledge graph construction and querying

**Technologies:** Google ADK · FastAPI · Neo4j · Vanilla JavaScript · SSE streaming · Ollama Cloud

**Demonstrates:**
- schema refinement loop (propose → critique → validate)
- deterministic Cypher generation
- SSE streaming query interface

**How it differs:** Graph-native knowledge representation and querying.

---

# 3. AI Safety & Quality Engineering

## 12. LLM Guardrails & AI Safety Defense Lab

**Folder:** [`03-AI-Safety-Quality/LLM-Guardrails/`](./03-AI-Safety-Quality/LLM-Guardrails/)

**Purpose:** A dedicated AI safety laboratory of guardrails — jailbreak defense, prompt-injection defense, topic controls, PII detection and output sanitization.

**Focus:** AI safety/guardrails controls

**Technologies:** NeMo Guardrails · Colang · Groq (Llama 3.1) · FastEmbed · regex actions

**Safety components:** Topic Guard · Jailbreak Shield · Sensitive Topic Block · Dialog Rails · PII Detector/Urgency · Output Sanitizer · Injection Detector/Content Sanitizer · System-Prompt-Leak Detector

**How it differs:** A dedicated safety laboratory — safety controls are the product, not a side feature.

---

## 13. AI-Safe Support Ticket Classifier

**Folder:** [`03-AI-Safety-Quality/Safe-Support-Ticket/`](./03-AI-Safety-Quality/Safe-Support-Ticket/)

**Purpose:** Secure LLM application design: PII redaction (pure regex, no ML/network call), prompt-injection detection via a separate judge LLM, and safe downstream workflow classification.

**Focus:** Security controls embedded in a practical AI business workflow

**Technologies:** LangGraph · FastAPI · Vanilla JS workflow visualizer · Ollama Cloud · gpt-oss:120b

**Demonstrates:**
- PII redaction (email, phone, credit-card) via pure regex
- injection categories: instruction override, role reassignment, prompt leak, new task injection, jailbreak framing, obfuscation
- separate judge LLM for injection detection

**How it differs:** Security controls inside a working business workflow — versus the Guardrails lab's isolated safety experiments.

---

# 4. Applied AI

## 14. DocFlow — AI Document Intelligence & Invoice Approval Engine

**Folder:** [`04-Applied-AI/DocFlow-Document-Intelligence/`](./04-Applied-AI/DocFlow-Document-Intelligence/) · **User guide:** [`userguide.html`](./04-Applied-AI/DocFlow-Document-Intelligence/userguide.html)

**Purpose:** Invoice-approval workflow where an LLM reads invoice PDFs (OCR fallback for image-only scans) with per-field confidence, but a deterministic engine — 9 validation checks, two/three-way PO matching, ordered policy rules R001–R008 — makes every financial decision, risky invoices go to an evidence-first human reviewer, and every stage lands in an append-only audit trail.

**Focus:** Document AI + deterministic validation/policy + human-in-the-loop approval

**Technologies:** FastAPI · Streamlit · SQLite · PyMuPDF · Tesseract OCR · Pillow · Pydantic v2 · Ollama (mock/live) · pytest (101 passed, 1 skipped)

**Architecture:**
```text
Invoice PDF → PyMuPDF text (quality-graded) → Tesseract OCR fallback (image-only)
→ LLM structured extraction + per-field confidence (Ollama or mock replay)
→ 9 deterministic checks + two/three-way PO match → Policy engine R001–R008 (first trigger wins)
→ AUTO_APPROVE (<¥100k) / EXCEPTION / HUMAN_REVIEW / FINANCE_REVIEW / REJECT (duplicate, pre-insert)
→ Evidence-first Streamlit review → SQLite systems of record + append-only audit trail
```

**Design principle:** *AI reads, code decides, humans own risk.*

**Evaluation:** 6-level harness over 10 seeded invoice scenarios (field accuracy with critical fields ×5, match accuracy, exception recall, false approvals, latency, review time saved). Shipped report: decision accuracy 1.0, exception recall 1.0, false approvals 0 — sample/project evaluation results, not production claims.

**How it differs:** Document AI where the LLM is deliberately untrusted — extraction only, with a pure-Python policy engine deciding, humans owning risk, and a replayable audit trail.

---

## 15. Research Voice Agent — AI Research-to-Podcast Pipeline

**Folder:** [`04-Applied-AI/Research-Voice-Agent/`](./04-Applied-AI/Research-Voice-Agent/)

**Purpose:** A multimodal/voice pipeline: research or transcripts are turned into a producer report, then a conversational script, then speech via TTS into an MP3.

**Focus:** Voice AI pipeline (STT → research → script → TTS)

**Technologies:** FastAPI · Google ADK · LiteLLM · gpt-oss:120b · DuckDuckGo search · yfinance · edge-tts · faster-whisper

**Modes:** AI News · Meeting Recap · Audio Summary

**Guardrails:** source-domain whitelist · freshness callback · process log · UI step tracker

**How it differs:** Multimodal/voice AI pipeline rather than text-only AI.

---

# 5. NLP & Machine Learning

## 16. NLP Machine Learning Sentiment Analysis Pipeline

**Folder:** [`05-NLP-Machine-Learning/Sentiment-Analysis/`](./05-NLP-Machine-Learning/Sentiment-Analysis/)

**Purpose:** A classical NLP/ML pipeline — preprocessing, TF-IDF feature engineering and supervised model comparison for sentiment classification.

**Focus:** Classical supervised NLP/ML (not an LLM project)

**Technologies:** scikit-learn · TF-IDF · Logistic Regression · Naive Bayes · NLTK · spaCy · Jupyter

**How it differs:** Demonstrates foundational NLP/ML knowledge alongside the modern LLM/agentic work in this portfolio.

---

# Differentiation Matrix

| Project | Primary Differentiator |
|---|---|
| AgentFlow | Dynamic multi-agent workflow/DAG generation |
| MCP Tool Orchestration | MCP tool ecosystem and tool calling |
| E-Commerce Multi-Agent | Hierarchical specialized agents |
| Order Returns & Fraud | Stateful business workflow + HITL |
| Hospital Appointment | LLM extraction + deterministic calendar |
| Multi-Agent Mindmap | 3-agent iterative review/refinement |
| Production RAG | Retrieval engineering + regression evaluation |
| Enterprise Knowledge Assistant | Hybrid vector + BM25 + graph retrieval |
| RAG Evaluation | RAG/LLM quality measurement |
| LLM Wiki | Document-to-knowledge-base generation |
| Knowledge Graph Builder | Graph-native knowledge construction/querying |
| LLM Guardrails | Dedicated AI safety controls |
| Safe Support Ticket | Security controls embedded in AI workflow |
| DocFlow | Document AI + deterministic validation/policy |
| Research Voice Agent | Voice/multimodal AI pipeline |
| Sentiment Analysis | Classical NLP/ML |

# Technology Coverage Table

| Technical Area | Technologies Demonstrated |
|---|---|
| LLM | Ollama, Ollama Cloud, Groq, LiteLLM |
| Agent Frameworks | Google ADK, LangGraph, LangChain, Agno |
| Tool Protocol | MCP |
| RAG | ChromaDB, Qdrant, LlamaIndex, Cognee |
| Knowledge Graph | Neo4j |
| Retrieval | BM25, Vector Search, Hybrid Retrieval, RRF |
| Evaluation | RAGAS, pytest, LLM-as-a-Judge |
| AI Safety | NeMo Guardrails, Colang, PII Detection, Injection Detection |
| Document AI | PyMuPDF, Tesseract OCR, Pydantic |
| Voice AI | faster-whisper, edge-tts |
| Backend | FastAPI |
| UI | Streamlit, React, Vanilla JavaScript |
| Databases | SQLite, ChromaDB, Qdrant, Neo4j |
| Classical NLP | scikit-learn, NLTK, spaCy |

> Per `instructions.md` §19, every technology above must be re-verified against actual project code during Phase 3 before final publication.