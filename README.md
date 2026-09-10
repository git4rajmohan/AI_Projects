<div align="center">

# 🧠 AI_Projects

**A curated showcase of AI and Machine Learning projects featuring local LLM workflows, multi-agent orchestration, RAG systems, model evaluation, automated AI testing frameworks, and classic NLP/ML text classification.**

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/🦜%20LangChain-LCEL-green)
![FastAPI](https://img.shields.io/badge/FastAPI-Web_APIs-009688?logo=fastapi&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud-white?logo=ollama)
![NeMo Guardrails](https://img.shields.io/badge/NVIDIA-NeMo%20Guardrails-76B900?logo=nvidia&logoColor=white)
![Google ADK](https://img.shields.io/badge/Google%20ADK-Multi--Agent%20Orchestration-4285F4?logo=google&logoColor=white)

</div>

---

## 📂 Projects

| # | Project | Stack | Status |
|---|---------|-------|--------|
| 1 | **[Hospital Appointment Scheduler & Confirmation Bot](./hospital-appointment-scheduler/)** | LangChain LCEL · FastAPI · Ollama Cloud (`gpt-oss:120b`) · Twilio SMS | ✅ Complete |
| 2 | **[Automated Order Returns & Fraud Prevention Agent](./langgraph-return-fraud-agent/)** | LangGraph · FastAPI · Streamlit · Ollama Cloud (`gpt-oss:120b`) · SQLite checkpointing | ✅ Complete |
| 3 | **[AI Guardrails Demo](./ai-guardrails-demo/)** | NeMo Guardrails · Streamlit · Groq Llama 3.x · BYOK | ✅ Complete |
| 4 | **[RAG Evaluation Harness](./rag-evaluation-harness/)** | RAGAS · Streamlit · OpenAI-compatible judge LLMs · pytest | ✅ Complete |
| 5 | **[Knowledge Graph Builder](./KnowledgegraphUIapp/)** | Google ADK · FastAPI · Neo4j · Ollama Cloud (`gpt-oss:120b`) · Vanilla JS | ✅ Complete |
| 6 | **[NLP Machine Learning Sentiment Analysis](./NLP_MachineLearning_SentimentAnalysis/)** | scikit-learn (TF-IDF · LR · NB · SVM) · NLTK · spaCy · Jupyter | ✅ Complete |
| 7 | **[Agentic AI Multi-Agent E-Commerce Orchestrator](./Agentic-AI-Ecommerce-Orchestrator/)** | Google ADK (4-agent hierarchy) · LiteLLM · Ollama Cloud (`gpt-oss:120b`) · `adk web` dev UI | ✅ Complete |
| 8 | **[Agentic AI Multi-Agent Mindmap Orchestrator](./agentic-ai-mindmap-orchestrator/)** | Streamlit · 3-agent review loop · Ollama Local (`gpt-oss:120b`) · markmap.js | ✅ Complete |
| 9 | **[Agentic AI MCP Tool Orchestration](./Agentic-AI-MCP-Tool-Orchestration/)** | MCP (14 tool servers over stdio) · Streamlit · Agno · Ollama Cloud (`gpt-oss:120b` + `glm-5.3-flash` vision) | ✅ Complete |
| 10 | **[AI-Safe Support Ticket Classifier](./AI-Safe-Support-Ticket-Classifier/)** | LangGraph · FastAPI · Vanilla JS workflow visualizer · Ollama Cloud (`gpt-oss:120b`) · LLM-judge injection guard | ✅ Complete |

### 1️⃣ Hospital Appointment Scheduler & Confirmation Bot

A production-style backend service + enterprise web console that processes natural-language appointment requests for a hospital: parses intent via LLM, checks calendar availability, books slots, and sends SMS confirmations.

**Highlights**

- 💬 Conversational booking bot — *"Book a cardiology appointment for John Doe next Monday at 2pm"*
- 🧩 LangChain LCEL pipeline with Pydantic v2 structured extraction
- 🖥️ Enterprise light-theme web console (sidebar shell, calendar, bookings, SMS audit trail)
- 📱 Real Twilio SMS integration with mock/seed/twilio modes
- 🗄️ SQLite persistence · 🧪 pytest suite (LLM mocked in unit tests)

> 📄 **Full docs, setup guide, API reference, and screenshots:** [`hospital-appointment-scheduler/README.md`](./hospital-appointment-scheduler/README.md) ·
> 📚 **In-depth technical documentation (HTML):** [`Documents/documentation.html`](./Documents/documentation.html)

| Chat Console | Calendar View |
|:---:|:---:|
| ![Chat](./hospital-appointment-scheduler/docs/screenshots/01-chat.png) | ![Calendar](./hospital-appointment-scheduler/docs/screenshots/02-calendar.png) |
| **Booking History** | **SMS History** |
| ![Bookings](./hospital-appointment-scheduler/docs/screenshots/03-bookings.png) | ![SMS](./hospital-appointment-scheduler/docs/screenshots/04-sms-history.png) |

---

### 2️⃣ Automated Order Returns & Fraud Prevention Agent

A LangGraph state-machine backend that automates e-commerce return/refund
decisions: policy checks, an LLM return-reason classifier, a cyclical
photo-proof loop, deterministic fraud scoring, and a native `interrupt()`
human-in-the-loop gate for manager approval on high-value or high-risk
refunds — all checkpointed to SQLite so runs survive server restarts.

**Highlights**

- 🧠 4-path workflow (auto-complete, photo-proof loop, manager approval, policy denial) in a single `StateGraph`
- 🤖 LLM return-reason classifier (Ollama Cloud `gpt-oss:120b`) with deterministic keyword fallback
- 🚦 Deterministic fraud scoring (return velocity, no-photo-after-retries, high refund amount)
- 🖥️ Streamlit console — Customer, Manager, and Pipeline (workflow-stage dashboard) views
- 🧪 149 pytest tests (unit + FastAPI integration)

> 📄 **Full docs, architecture, setup guide, and screenshots:** [`langgraph-return-fraud-agent/README.md`](./langgraph-return-fraud-agent/README.md)

| Customer view | Workflow pipeline dashboard |
|:---:|:---:|
| ![Customer](./langgraph-return-fraud-agent/docs/screenshots/01-customer.png) | ![Pipeline](./langgraph-return-fraud-agent/docs/screenshots/02-pipeline.png) |
| **Manager console** | **API reference** |
| ![Manager](./langgraph-return-fraud-agent/docs/screenshots/03-manager.png) | ![API docs](./langgraph-return-fraud-agent/docs/screenshots/04-api-docs.png) |

---

### 3️⃣ AI Guardrails Demo

An interactive Streamlit teaching app for **NVIDIA NeMo Guardrails**: 7 progressive experiments that layer safety rails onto a raw LLM — from zero protection to a production-grade guarded Enterprise IT Assistant (Kubernetes · Intel hardware · enterprise networking). Users bring their own Groq API key (BYOK) and watch each rail block a different class of abuse.

**Highlights**

- 🛡️ 7 cumulative experiments — Topic Guard, Jailbreak Shield, Sensitive Topic Block, Dialog Rails, Custom Actions, Output Sanitizer
- 📝 Colang DSL in action — `define user / define bot / define flow` with semantic intent matching via FastEmbed + guard LLM
- 🐍 Custom `@action` Python rails — PII regex scanner, urgency classifier, credential sanitizer, prompt-injection detector
- 🟠 Bonus prompt-injection lab — hidden-in-data attacks with a Without-Rails vs With-Rails comparison
- 📊 Token & latency tracking per LLM call, plus optional Logfire (OpenTelemetry) tracing
- 🔐 BYOK security — keys entered at runtime as password fields, never stored, logged, or committed

> 📄 **Full docs, theory reference, setup guide, and screenshots:** [`ai-guardrails-demo/README.md`](./ai-guardrails-demo/README.md)

| Landing & experiment map | Input Rails — Topic Guard |
|:---:|:---:|
| ![Landing](./ai-guardrails-demo/docs/screenshots/02-landing-expanded.png) | ![Input Rails](./ai-guardrails-demo/docs/screenshots/04-input-rails.png) |
| **Custom Python Actions** | **Prompt Injection lab** |
| ![Custom Actions](./ai-guardrails-demo/docs/screenshots/05-custom-actions.png) | ![Prompt Injection](./ai-guardrails-demo/docs/screenshots/07-prompt-injection.png) |

---

### 4️⃣ RAG Evaluation Harness

A Streamlit evaluation workbench for RAG systems built on **RAGAS**: point it at any RAG endpoint plus any OpenAI-compatible judge LLM and step through a two-phase workflow — query the RAG, review the retrieved contexts, then score quality with 7 LLM-judged (no-embedding) metrics, complete with pass/fail thresholds, per-metric reasoning, and JSON run history.

**Highlights**

- 🧑‍⚖️ 7 no-embedding RAGAS metrics — context relevance/precision/recall, groundedness, faithfulness, factual correctness, rubrics score
- 🔁 Two-phase human-in-the-loop workflow — review retrieved contexts *before* scoring so bad retrievals never silently skew results
- 🖥️ Streamlit workbench — editable data grid, metric multi-select, gauge dashboard with recommended ranges
- 💬 Multi-turn evaluation — Topic Adherence & Faithfulness across a full conversation, editable turn-by-turn
- 💾 Run history as timestamped JSON files — save/reload/delete evaluations with zero database overhead
- 🌐 Endpoint-agnostic — local Ollama, Baseten, OpenAI, or Azure OpenAI judge LLMs
- 🧪 pytest suite (`Test1`–`Test7`) doubles as a CI regression gate for every metric

> 📄 **Full docs, setup guide, and screenshots:** [`rag-evaluation-harness/README.md`](./rag-evaluation-harness/README.md)

| Config — pick metrics & judge LLM | Multi-turn conversation evaluation |
|:---:|:---:|
| ![Config](./rag-evaluation-harness/docs/screenshots/01-config.png) | ![Multi-turn](./rag-evaluation-harness/docs/screenshots/02-multiturn.png) |

---

### 5️⃣ Knowledge Graph Builder

A web application that automates the creation of knowledge graphs from structured data files (CSV) and unstructured text (Markdown). A team of AI agents (Google ADK `LoopAgent`) iteratively proposes, critiques, and validates a graph schema, then constructs the graph in Neo4j, and finally lets you query it using natural language — all through a clean web UI with live agent progress streaming.

**Highlights**

- 🤖 3-agent refinement loop (Proposer → Critic → Checker, max 3 iterations) for schema proposal via Google ADK
- 📁 File browser — select CSV, Markdown, or JSON files from any folder
- 🏗️ One-click graph building — auto-creates Neo4j DB, copies CSVs via `docker cp`, runs Cypher `LOAD CSV` + `MERGE`
- 🔍 Natural language Q&A — AI agent translates questions to Cypher, executes, and summarizes results
- 📊 Interactive Canvas graph visualization with zoom/pan/drag
- 📡 SSE streaming for real-time agent activity during schema proposal
- 🗄️ Multi-database isolation — each project gets its own Neo4j database
- 📋 6 sample datasets — Furniture, Tech, Reviews, Healthcare, E-commerce, Education

> 📄 **Full docs, setup guide, architecture, and screenshots:** [`KnowledgegraphUIapp/README.md`](./KnowledgegraphUIapp/README.md) ·
> 📚 **Interactive user guide (HTML, 2 tabs):** [`KnowledgegraphUIapp/userguide.html`](./KnowledgegraphUIapp/userguide.html)

| User Guide — How It Works | User Guide — Technical Details |
|:---:|:---:|
| ![Tab 1](./KnowledgegraphUIapp/images/userguide-tab1-full.png) | ![Tab 2](./KnowledgegraphUIapp/images/userguide-tab2-full.png) |

---

### 6️⃣ NLP Machine Learning Sentiment Analysis

A complete, educational Jupyter notebook that walks through the **full NLP pipeline** for 3-class sentiment analysis (Positive / Neutral / Negative) on a custom ~2,000-review dataset — every step visualized and explained, from raw noisy text cleaning to a trained, explained, and saved ML model.

**Highlights**

- 🧹 12-function preprocessing pipeline (URL/emoji/HTML removal, tokenization, stop words with **negation retention**, POS-aware lemmatization via spaCy)
- 📐 TF-IDF feature extraction with n-gram vocabulary and top-feature inspection
- 🤖 Three models compared head-to-head — Logistic Regression (99.75%), Naive Bayes (99.25%), Linear SVM (**100%**)
- ⚖️ Rule-based baselines benchmarked against ML — TextBlob (59.1%) and VADER (84.0%)
- 🔍 Prediction explainability via LR feature coefficients
- 📊 Word clouds, sentiment distribution, and confusion matrix visualizations
- 🏗️ FastAPI-ready — `preprocessing.py` + saved `.pkl` artifacts drop straight into a web backend
- 📖 Self-contained interactive **user guide** (`userguide.html`, 22 pages) in plain language for non-technical readers

> 📄 **Full docs, setup guide, and results:** [`NLP_MachineLearning_SentimentAnalysis/README.md`](./NLP_MachineLearning_SentimentAnalysis/README.md) ·
> 📚 **Interactive user guide (HTML, 22 pages):** [`NLP_MachineLearning_SentimentAnalysis/userguide.html`](./NLP_MachineLearning_SentimentAnalysis/userguide.html)

| Sentiment Distribution | Confusion Matrix (Linear SVM) |
|:---:|:---:|
| ![Distribution](./NLP_MachineLearning_SentimentAnalysis/outputs/sentiment_distribution.png) | ![Confusion Matrix](./NLP_MachineLearning_SentimentAnalysis/outputs/confusion_matrix.png) |
| **User Guide — Overview** | **User Guide — Word Clouds** |
| ![Guide Overview](./NLP_MachineLearning_SentimentAnalysis/images/userguide-overview.png) | ![Guide Word Clouds](./NLP_MachineLearning_SentimentAnalysis/images/userguide-wordclouds.png) |

---

### 7️⃣ Agentic AI Multi-Agent E-Commerce Orchestrator

A multi-agent e-commerce assistant built on **Google ADK**: a root orchestrator collects the shopper's profile and delegates to three specialist agents — catalog (browse & cart), checkout (shipping address), and order summary — which coordinate the full purchase flow through **shared session state**, ending in an Amazon-style order summary. Runs entirely on Ollama Cloud (`gpt-oss:120b`) via LiteLLM.

**Highlights**

- 🤖 4-agent hierarchy — `ecommerce_agent` (root) → `catalog_agent` → `checkout_agent` → `order_summary_agent` with `transfer_to_agent` delegation
- 🔐 Workflow gating — checkout is blocked until user profile (name/email/mobile) is saved to session state
- 🚌 Session state as the data bus — tools write `tool_context.state`; downstream agents read `{item} {quantity} {price} {shipping_address}` template variables
- 🛠️ Function tools — `save_user_info`, `save_cart`, `save_shipping_address` persist workflow data across agents
- 🧠 Tool-calling on open models — LiteLLM `openai/` provider against Ollama Cloud (native `format: json` breaks tool calling)
- 🔍 Full observability — `adk web` dev UI with event traces, agent-transfer graph, and live state inspector
- 📖 Self-contained interactive **user guide** (`userguide.html`) in plain language

> 📄 **Full docs, setup guide, and architecture:** [`Agentic-AI-Ecommerce-Orchestrator/README.md`](./Agentic-AI-Ecommerce-Orchestrator/README.md) ·
> 📚 **Interactive user guide (HTML):** [`Agentic-AI-Ecommerce-Orchestrator/userguide.html`](./Agentic-AI-Ecommerce-Orchestrator/userguide.html)

| Order summary (end-to-end result) | Session state — the data bus |
|:---:|:---:|
| ![Order Summary](./Agentic-AI-Ecommerce-Orchestrator/docs/screenshots/06-order-summary.png) | ![Session State](./Agentic-AI-Ecommerce-Orchestrator/docs/screenshots/07-session-state.png) |
| **Catalog browsing** | **Cart saved + checkout handoff** |
| ![Catalog](./Agentic-AI-Ecommerce-Orchestrator/docs/screenshots/03-catalog-agent.png) | ![Cart](./Agentic-AI-Ecommerce-Orchestrator/docs/screenshots/05-cart-saved.png) |

---

### 8️⃣ Agentic AI Multi-Agent Mindmap Orchestrator

An agentic pipeline that transforms unstructured content — text files, YouTube transcripts, pasted text — into **interactive mindmaps** using a collaborative **Creator → Reviewer → Reviser** agent workflow on a **local Ollama LLM**. The Schema Creator proposes a JSON mindmap schema, the Reviewer grades it against six quality criteria (coverage, balance, conciseness, hierarchy, accuracy, validity), and the Reviser iterates until approval — demonstrating agent orchestration, iterative feedback loops, LLM output validation, and deterministic artifact generation.

**Highlights**

- 🤖 3-agent review loop — Schema Creator ⇄ Schema Reviewer (6 criteria) with feedback-driven revision, up to 5 iterations
- ⚡ Dual mode — Fast single-pass generation or quality-first Agent Mode with live progress streaming
- ✅ LLM output validation — code-fence stripping + JSON parsing with graceful max-iteration degradation
- 🎨 Deterministic rendering — approved schema → Markdown via pure-Python converter (no LLM in the final step)
- 🗺️ Interactive markmap visualizations — collapsible SVG, hover tooltips, in-app live Markdown editing
- ⬇️ Standalone HTML export — portable, offline-openable mindmap artifacts
- 🔒 100% local — Ollama on localhost; no cloud APIs, no data leaving the machine

> 📄 **Full docs, setup guide, and architecture:** [`agentic-ai-mindmap-orchestrator/README.md`](./agentic-ai-mindmap-orchestrator/README.md) ·
> 📚 **Interactive user guide (HTML, 2 tabs):** [`agentic-ai-mindmap-orchestrator/userguide.html`](./agentic-ai-mindmap-orchestrator/userguide.html)

| System architecture | GitHub social preview |
|:---:|:---:|
| ![Architecture](./agentic-ai-mindmap-orchestrator/docs/architecture.svg) | ![Social preview](./agentic-ai-mindmap-orchestrator/images/github-social-preview.svg) |

---

### 9️⃣ Agentic AI — MCP Tool Orchestration

A production-style AI chat assistant that orchestrates **14 MCP (Model Context Protocol) tool servers** behind any LLM — time, Excel, filesystem, browser automation, draw.io diagrams, charts, SQL, Jira, AgilePoint docs/worklists, and image understanding — via a Streamlit chat UI with a switchable provider layer (Ollama Cloud `gpt-oss:120b` main + `glm-5.3-flash` vision, local Ollama, or any OpenAI-compatible endpoint such as Baseten).

**Highlights**

- 🧩 MCP-standard tools — any MCP-compatible server plugs in via `mcp_servers.yaml` with zero code changes (stdio JSON-RPC subprocesses, crash-isolated)
- 🔀 Provider-agnostic LLM layer — main + dedicated vision model independently switchable; secrets via `.env.llm`, never committed
- 🛡️ Robust turn handling — transient tool failures auto-retry (timeouts/transport only), Excel turns auto-scoped to Excel-only tools (quoted/UNC/plain paths), draw.io link + commentary composition
- 🎛️ Guardrails — approval mode, tool allow/deny policies, row ceilings injected per server (`EXCEL_MAX_ROWS`, `SQL_MAX_ROWS`), output truncation with full-output expander
- 🔍 Full observability — per-session JSONL traces with secret redaction, tool-call expanders showing exact payloads
- 🧪 Quality gates — pytest (44 passed), live preflight harness that starts a real Excel MCP server, 12-recipe manual E2E plan with test-data generators
- 📖 Interactive 2-tab `userguide.html` (everyday guide + full technical reference)

> 📚 **Full docs, setup guide, and architecture:** [`Agentic-AI-MCP-Tool-Orchestration/README.md`](./Agentic-AI-MCP-Tool-Orchestration/README.md) ·
> 📖 **Interactive user guide (HTML, 2 tabs):** [`Agentic-AI-MCP-Tool-Orchestration/userguide.html`](./Agentic-AI-MCP-Tool-Orchestration/userguide.html) ·
> 🧪 **Manual E2E test plan:** [`Agentic-AI-MCP-Tool-Orchestration/howtotest.md`](./Agentic-AI-MCP-Tool-Orchestration/howtotest.md)

---

### 🔟 AI-Safe Support Ticket Classifier

A production-grade AI ticket-triage service with a **live pipeline visualizer**: a 6-node LangGraph pipeline wraps an LLM classifier in hard safety boundaries — PII redaction before the model ever sees the text, a dedicated LLM-judge prompt-injection guard that fails closed, Pydantic schema + business-rule validation, and a tenacity-backed fallback so a ticket is never lost. Every node's status (green/red/grey + yellow replay pulse), duration, and full output is inspectable in the browser via a per-node trace contract.

**Highlights**

- 🧠 Structured classification — 7 issue categories · 5 team owners · 4 priorities · 4 sentiments · confidence + reasoning, via JSON-mode on Ollama Cloud (`gpt-oss:120b`)
- 🛡️ PII redaction first — regex engine strips EMAIL / PHONE / CREDIT_CARD before any LLM call; the original text never leaves the server
- 🚨 Prompt-injection guard — dedicated LLM judge with structured verdict; **fails safe** (guard error ⇒ block input, not pass-through)
- 📊 Live workflow visualizer — color-coded node strip (green completed / red failed / yellow pulsing / grey skipped) with per-node durations and SVG edges, including the fallback branch
- 🔍 Node detail inspector — click any node for a slide-over drawer: redacted text, PII chips, guard verdict + attack pattern, full classification, validation errors, cost breakdown, raw JSON
- 🔁 Safe fallback — tenacity retries → conservative `SAFE_CLASSIFICATION` (human review, confidence 0)
- 💰 Cost & prompt-version tracking — per-call token/cost roll-up, versioned prompt registry stamped on every result
- 📖 Two-tier in-app user guide (`userguide.html`) — a non-technical explainer tab and a technical architecture tab
- 🧪 8 offline pytest tests (LLM mocked), all passing

> 📄 **Full docs, setup guide, and architecture:** [`AI-Safe-Support-Ticket-Classifier/README.md`](./AI-Safe-Support-Ticket-Classifier/README.md) ·
> 📚 **Interactive user guide (HTML, 2 tabs):** [`AI-Safe-Support-Ticket-Classifier/demo_ui/userguide.html`](./AI-Safe-Support-Ticket-Classifier/demo_ui/userguide.html)

| Green path — clean run w/ PII redaction | Red path — injection attack blocked |
|:---:|:---:|
| ![Green path](./AI-Safe-Support-Ticket-Classifier/docs/images/01_green_path.png) | ![Injection blocked](./AI-Safe-Support-Ticket-Classifier/docs/images/02_injection_blocked.png) |
| **Node inspector — PII drawer** | **Two-tier user guide** |
| ![Node drawer](./AI-Safe-Support-Ticket-Classifier/docs/images/03_node_drawer.png) | ![User guide](./AI-Safe-Support-Ticket-Classifier/docs/images/04_userguide.png) |

| Architecture | GitHub social preview |
|:---:|:---:|
| ![Architecture](./Agentic-AI-MCP-Tool-Orchestration/docs/architecture.png) | ![Social preview](./Agentic-AI-MCP-Tool-Orchestration/images/github-social-preview.png) |

---

## 🗺️ Roadmap

- [x] 5️⃣ Knowledge Graph Builder — ADK agents + Neo4j + natural language Q&A → **[KnowledgegraphUIapp](./KnowledgegraphUIapp/)**
- [x] 6️⃣ Model Evaluation Harness — automated LLM benchmarking & regression testing → **[rag-evaluation-harness](./rag-evaluation-harness/)**
- [x] 7️⃣ Classic NLP / ML Sentiment Analysis — end-to-end text classification teaching notebook → **[NLP_MachineLearning_SentimentAnalysis](./NLP_MachineLearning_SentimentAnalysis/)**
- [x] 8️⃣ Multi-Agent Workflow Orchestrator — ADK-style agent collaboration patterns → **[Agentic-AI-Ecommerce-Orchestrator](./Agentic-AI-Ecommerce-Orchestrator/)**
- [x] 9️⃣ MCP Tool Orchestration — Model Context Protocol client + 14 tool servers → **[Agentic-AI-MCP-Tool-Orchestration](./Agentic-AI-MCP-Tool-Orchestration/)**

## 🛠️ Common Tech

| Layer | Tools |
|-------|-------|
| LLM Orchestration | LangChain (LCEL), LangGraph, Google ADK, NVIDIA NeMo Guardrails, **MCP (Model Context Protocol)**, Agno |
| Evaluation | RAGAS (LLM-judged metrics), pytest, Streamlit dashboards |
| LLM Providers | Ollama Cloud (gpt-oss:120b, glm-5.2, kimi-k2.6), local Ollama |
| APIs & UI | FastAPI, Uvicorn, Streamlit, vanilla-JS enterprise consoles |
| Data & Validation | Pydantic v2, SQLite |
| Testing | pytest, pytest-asyncio |
| Integrations | Twilio (SMS), Neo4j (graph data) |
| Classic NLP / ML | scikit-learn (TF-IDF, LR, NB, SVM), NLTK, spaCy, TextBlob, VADER |

---

<div align="center">

**Each project is self-contained** in its own folder with independent setup, `.env.example`, and tests.

</div>