<div align="center">

# 🧠 AI_Projects

**A curated showcase of AI and Machine Learning projects featuring local LLM workflows, RAG systems, model evaluation, and automated AI testing frameworks.**

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/🦜%20LangChain-LCEL-green)
![FastAPI](https://img.shields.io/badge/FastAPI-Web_APIs-009688?logo=fastapi&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud-white?logo=ollama)
![NeMo Guardrails](https://img.shields.io/badge/NVIDIA-NeMo%20Guardrails-76B900?logo=nvidia&logoColor=white)

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

## 🗺️ Roadmap

- [x] 5️⃣ Knowledge Graph Builder — ADK agents + Neo4j + natural language Q&A → **[KnowledgegraphUIapp](./KnowledgegraphUIapp/)**
- [x] 6️⃣ Model Evaluation Harness — automated LLM benchmarking & regression testing → **[rag-evaluation-harness](./rag-evaluation-harness/)**
- [ ] 7️⃣ Multi-Agent Workflow Orchestrator — ADK-style agent collaboration patterns

## 🛠️ Common Tech

| Layer | Tools |
|-------|-------|
| LLM Orchestration | LangChain (LCEL), LangGraph, Google ADK, NVIDIA NeMo Guardrails |
| Evaluation | RAGAS (LLM-judged metrics), pytest, Streamlit dashboards |
| LLM Providers | Ollama Cloud (gpt-oss:120b, glm-5.2, kimi-k2.6), local Ollama |
| APIs & UI | FastAPI, Uvicorn, Streamlit, vanilla-JS enterprise consoles |
| Data & Validation | Pydantic v2, SQLite |
| Testing | pytest, pytest-asyncio |
| Integrations | Twilio (SMS), Neo4j (graph data) |

---

<div align="center">

**Each project is self-contained** in its own folder with independent setup, `.env.example`, and tests.

</div>