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

## 🗺️ Roadmap

- [ ] 4️⃣ RAG Knowledge Base — document Q&A with local embeddings + Neo4j GraphRAG
- [ ] 5️⃣ Model Evaluation Harness — automated LLM benchmarking & regression testing
- [ ] 6️⃣ Multi-Agent Workflow Orchestrator — ADK-style agent collaboration patterns

## 🛠️ Common Tech

| Layer | Tools |
|-------|-------|
| LLM Orchestration | LangChain (LCEL), LangGraph, Google ADK, NVIDIA NeMo Guardrails |
| LLM Providers | Ollama Cloud (gpt-oss:120b, glm-5.2, kimi-k2.6), local Ollama |
| APIs & UI | FastAPI, Uvicorn, Streamlit, vanilla-JS enterprise consoles |
| Data & Validation | Pydantic v2, SQLite |
| Testing | pytest, pytest-asyncio |
| Integrations | Twilio (SMS), Neo4j (graph data) |

---

<div align="center">

**Each project is self-contained** in its own folder with independent setup, `.env.example`, and tests.

</div>