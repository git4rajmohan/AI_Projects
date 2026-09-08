<div align="center">

# ｧ AI_Projects

**A curated showcase of AI and Machine Learning projects featuring local LLM workflows, multi-agent orchestration, RAG systems, model evaluation, automated AI testing frameworks, and classic NLP/ML text classification.**

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/ｦ・20LangChain-LCEL-green)
![FastAPI](https://img.shields.io/badge/FastAPI-Web_APIs-009688?logo=fastapi&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20Cloud-white?logo=ollama)
![NeMo Guardrails](https://img.shields.io/badge/NVIDIA-NeMo%20Guardrails-76B900?logo=nvidia&logoColor=white)
![Google ADK](https://img.shields.io/badge/Google%20ADK-Multi--Agent%20Orchestration-4285F4?logo=google&logoColor=white)

</div>

---

## 唐 Projects

| # | Project | Stack | Status |
|---|---------|-------|--------|
| 1 | **[Hospital Appointment Scheduler & Confirmation Bot](./hospital-appointment-scheduler/)** | LangChain LCEL ﾂｷ FastAPI ﾂｷ Ollama Cloud (`gpt-oss:120b`) ﾂｷ Twilio SMS | 笨・Complete |
| 2 | **[Automated Order Returns & Fraud Prevention Agent](./langgraph-return-fraud-agent/)** | LangGraph ﾂｷ FastAPI ﾂｷ Streamlit ﾂｷ Ollama Cloud (`gpt-oss:120b`) ﾂｷ SQLite checkpointing | 笨・Complete |
| 3 | **[AI Guardrails Demo](./ai-guardrails-demo/)** | NeMo Guardrails ﾂｷ Streamlit ﾂｷ Groq Llama 3.x ﾂｷ BYOK | 笨・Complete |
| 4 | **[RAG Evaluation Harness](./rag-evaluation-harness/)** | RAGAS ﾂｷ Streamlit ﾂｷ OpenAI-compatible judge LLMs ﾂｷ pytest | 笨・Complete |
| 5 | **[Knowledge Graph Builder](./KnowledgegraphUIapp/)** | Google ADK ﾂｷ FastAPI ﾂｷ Neo4j ﾂｷ Ollama Cloud (`gpt-oss:120b`) ﾂｷ Vanilla JS | 笨・Complete |
| 6 | **[NLP Machine Learning Sentiment Analysis](./NLP_MachineLearning_SentimentAnalysis/)** | scikit-learn (TF-IDF ﾂｷ LR ﾂｷ NB ﾂｷ SVM) ﾂｷ NLTK ﾂｷ spaCy ﾂｷ Jupyter | 笨・Complete |
| 7 | **[Agentic AI Multi-Agent E-Commerce Orchestrator](./Agentic-AI-Ecommerce-Orchestrator/)** | Google ADK (4-agent hierarchy) ﾂｷ LiteLLM ﾂｷ Ollama Cloud (`gpt-oss:120b`) ﾂｷ `adk web` dev UI | 笨・Complete |
| 8 | **[Agentic AI Multi-Agent Mindmap Orchestrator](./agentic-ai-mindmap-orchestrator/)** | Streamlit ﾂｷ 3-agent review loop ﾂｷ Ollama Local (`gpt-oss:120b`) ﾂｷ markmap.js | 笨・Complete |

### 1・鞘Ε Hospital Appointment Scheduler & Confirmation Bot

A production-style backend service + enterprise web console that processes natural-language appointment requests for a hospital: parses intent via LLM, checks calendar availability, books slots, and sends SMS confirmations.

**Highlights**

- 町 Conversational booking bot 窶・*"Book a cardiology appointment for John Doe next Monday at 2pm"*
- ｧｩ LangChain LCEL pipeline with Pydantic v2 structured extraction
- 箕・・Enterprise light-theme web console (sidebar shell, calendar, bookings, SMS audit trail)
- 導 Real Twilio SMS integration with mock/seed/twilio modes
- 淀・・SQLite persistence ﾂｷ ｧｪ pytest suite (LLM mocked in unit tests)

> 塘 **Full docs, setup guide, API reference, and screenshots:** [`hospital-appointment-scheduler/README.md`](./hospital-appointment-scheduler/README.md) ﾂｷ
> 答 **In-depth technical documentation (HTML):** [`Documents/documentation.html`](./Documents/documentation.html)

| Chat Console | Calendar View |
|:---:|:---:|
| ![Chat](./hospital-appointment-scheduler/docs/screenshots/01-chat.png) | ![Calendar](./hospital-appointment-scheduler/docs/screenshots/02-calendar.png) |
| **Booking History** | **SMS History** |
| ![Bookings](./hospital-appointment-scheduler/docs/screenshots/03-bookings.png) | ![SMS](./hospital-appointment-scheduler/docs/screenshots/04-sms-history.png) |

---

### 2・鞘Ε Automated Order Returns & Fraud Prevention Agent

A LangGraph state-machine backend that automates e-commerce return/refund
decisions: policy checks, an LLM return-reason classifier, a cyclical
photo-proof loop, deterministic fraud scoring, and a native `interrupt()`
human-in-the-loop gate for manager approval on high-value or high-risk
refunds 窶・all checkpointed to SQLite so runs survive server restarts.

**Highlights**

- ｧ 4-path workflow (auto-complete, photo-proof loop, manager approval, policy denial) in a single `StateGraph`
- ､・LLM return-reason classifier (Ollama Cloud `gpt-oss:120b`) with deterministic keyword fallback
- 圜 Deterministic fraud scoring (return velocity, no-photo-after-retries, high refund amount)
- 箕・・Streamlit console 窶・Customer, Manager, and Pipeline (workflow-stage dashboard) views
- ｧｪ 149 pytest tests (unit + FastAPI integration)

> 塘 **Full docs, architecture, setup guide, and screenshots:** [`langgraph-return-fraud-agent/README.md`](./langgraph-return-fraud-agent/README.md)

| Customer view | Workflow pipeline dashboard |
|:---:|:---:|
| ![Customer](./langgraph-return-fraud-agent/docs/screenshots/01-customer.png) | ![Pipeline](./langgraph-return-fraud-agent/docs/screenshots/02-pipeline.png) |
| **Manager console** | **API reference** |
| ![Manager](./langgraph-return-fraud-agent/docs/screenshots/03-manager.png) | ![API docs](./langgraph-return-fraud-agent/docs/screenshots/04-api-docs.png) |

---

### 3・鞘Ε AI Guardrails Demo

An interactive Streamlit teaching app for **NVIDIA NeMo Guardrails**: 7 progressive experiments that layer safety rails onto a raw LLM 窶・from zero protection to a production-grade guarded Enterprise IT Assistant (Kubernetes ﾂｷ Intel hardware ﾂｷ enterprise networking). Users bring their own Groq API key (BYOK) and watch each rail block a different class of abuse.

**Highlights**

- 孱・・7 cumulative experiments 窶・Topic Guard, Jailbreak Shield, Sensitive Topic Block, Dialog Rails, Custom Actions, Output Sanitizer
- 統 Colang DSL in action 窶・`define user / define bot / define flow` with semantic intent matching via FastEmbed + guard LLM
- 錐 Custom `@action` Python rails 窶・PII regex scanner, urgency classifier, credential sanitizer, prompt-injection detector
- 泛 Bonus prompt-injection lab 窶・hidden-in-data attacks with a Without-Rails vs With-Rails comparison
- 投 Token & latency tracking per LLM call, plus optional Logfire (OpenTelemetry) tracing
- 柏 BYOK security 窶・keys entered at runtime as password fields, never stored, logged, or committed

> 塘 **Full docs, theory reference, setup guide, and screenshots:** [`ai-guardrails-demo/README.md`](./ai-guardrails-demo/README.md)

| Landing & experiment map | Input Rails 窶・Topic Guard |
|:---:|:---:|
| ![Landing](./ai-guardrails-demo/docs/screenshots/02-landing-expanded.png) | ![Input Rails](./ai-guardrails-demo/docs/screenshots/04-input-rails.png) |
| **Custom Python Actions** | **Prompt Injection lab** |
| ![Custom Actions](./ai-guardrails-demo/docs/screenshots/05-custom-actions.png) | ![Prompt Injection](./ai-guardrails-demo/docs/screenshots/07-prompt-injection.png) |

---

### 4・鞘Ε RAG Evaluation Harness

A Streamlit evaluation workbench for RAG systems built on **RAGAS**: point it at any RAG endpoint plus any OpenAI-compatible judge LLM and step through a two-phase workflow 窶・query the RAG, review the retrieved contexts, then score quality with 7 LLM-judged (no-embedding) metrics, complete with pass/fail thresholds, per-metric reasoning, and JSON run history.

**Highlights**

- ｧ鯛坂囑・・7 no-embedding RAGAS metrics 窶・context relevance/precision/recall, groundedness, faithfulness, factual correctness, rubrics score
- 煤 Two-phase human-in-the-loop workflow 窶・review retrieved contexts *before* scoring so bad retrievals never silently skew results
- 箕・・Streamlit workbench 窶・editable data grid, metric multi-select, gauge dashboard with recommended ranges
- 町 Multi-turn evaluation 窶・Topic Adherence & Faithfulness across a full conversation, editable turn-by-turn
- 沈 Run history as timestamped JSON files 窶・save/reload/delete evaluations with zero database overhead
- 倹 Endpoint-agnostic 窶・local Ollama, Baseten, OpenAI, or Azure OpenAI judge LLMs
- ｧｪ pytest suite (`Test1`窶伝Test7`) doubles as a CI regression gate for every metric

> 塘 **Full docs, setup guide, and screenshots:** [`rag-evaluation-harness/README.md`](./rag-evaluation-harness/README.md)

| Config 窶・pick metrics & judge LLM | Multi-turn conversation evaluation |
|:---:|:---:|
| ![Config](./rag-evaluation-harness/docs/screenshots/01-config.png) | ![Multi-turn](./rag-evaluation-harness/docs/screenshots/02-multiturn.png) |

---

### 5・鞘Ε Knowledge Graph Builder

A web application that automates the creation of knowledge graphs from structured data files (CSV) and unstructured text (Markdown). A team of AI agents (Google ADK `LoopAgent`) iteratively proposes, critiques, and validates a graph schema, then constructs the graph in Neo4j, and finally lets you query it using natural language 窶・all through a clean web UI with live agent progress streaming.

**Highlights**

- ､・3-agent refinement loop (Proposer 竊・Critic 竊・Checker, max 3 iterations) for schema proposal via Google ADK
- 刀 File browser 窶・select CSV, Markdown, or JSON files from any folder
- 女・・One-click graph building 窶・auto-creates Neo4j DB, copies CSVs via `docker cp`, runs Cypher `LOAD CSV` + `MERGE`
- 剥 Natural language Q&A 窶・AI agent translates questions to Cypher, executes, and summarizes results
- 投 Interactive Canvas graph visualization with zoom/pan/drag
- 藤 SSE streaming for real-time agent activity during schema proposal
- 淀・・Multi-database isolation 窶・each project gets its own Neo4j database
- 搭 6 sample datasets 窶・Furniture, Tech, Reviews, Healthcare, E-commerce, Education

> 塘 **Full docs, setup guide, architecture, and screenshots:** [`KnowledgegraphUIapp/README.md`](./KnowledgegraphUIapp/README.md) ﾂｷ
> 答 **Interactive user guide (HTML, 2 tabs):** [`KnowledgegraphUIapp/userguide.html`](./KnowledgegraphUIapp/userguide.html)

| User Guide 窶・How It Works | User Guide 窶・Technical Details |
|:---:|:---:|
| ![Tab 1](./KnowledgegraphUIapp/images/userguide-tab1-full.png) | ![Tab 2](./KnowledgegraphUIapp/images/userguide-tab2-full.png) |

---

### 6・鞘Ε NLP Machine Learning Sentiment Analysis

A complete, educational Jupyter notebook that walks through the **full NLP pipeline** for 3-class sentiment analysis (Positive / Neutral / Negative) on a custom ~2,000-review dataset 窶・every step visualized and explained, from raw noisy text cleaning to a trained, explained, and saved ML model.

**Highlights**

- ｧｹ 12-function preprocessing pipeline (URL/emoji/HTML removal, tokenization, stop words with **negation retention**, POS-aware lemmatization via spaCy)
- 盗 TF-IDF feature extraction with n-gram vocabulary and top-feature inspection
- ､・Three models compared head-to-head 窶・Logistic Regression (99.75%), Naive Bayes (99.25%), Linear SVM (**100%**)
- 笞厄ｸ・Rule-based baselines benchmarked against ML 窶・TextBlob (59.1%) and VADER (84.0%)
- 剥 Prediction explainability via LR feature coefficients
- 投 Word clouds, sentiment distribution, and confusion matrix visualizations
- 女・・FastAPI-ready 窶・`preprocessing.py` + saved `.pkl` artifacts drop straight into a web backend
- 当 Self-contained interactive **user guide** (`userguide.html`, 22 pages) in plain language for non-technical readers

> 塘 **Full docs, setup guide, and results:** [`NLP_MachineLearning_SentimentAnalysis/README.md`](./NLP_MachineLearning_SentimentAnalysis/README.md) ﾂｷ
> 答 **Interactive user guide (HTML, 22 pages):** [`NLP_MachineLearning_SentimentAnalysis/userguide.html`](./NLP_MachineLearning_SentimentAnalysis/userguide.html)

| Sentiment Distribution | Confusion Matrix (Linear SVM) |
|:---:|:---:|
| ![Distribution](./NLP_MachineLearning_SentimentAnalysis/outputs/sentiment_distribution.png) | ![Confusion Matrix](./NLP_MachineLearning_SentimentAnalysis/outputs/confusion_matrix.png) |
| **User Guide 窶・Overview** | **User Guide 窶・Word Clouds** |
| ![Guide Overview](./NLP_MachineLearning_SentimentAnalysis/images/userguide-overview.png) | ![Guide Word Clouds](./NLP_MachineLearning_SentimentAnalysis/images/userguide-wordclouds.png) |

---

### 7・鞘Ε Agentic AI Multi-Agent E-Commerce Orchestrator

A multi-agent e-commerce assistant built on **Google ADK**: a root orchestrator collects the shopper's profile and delegates to three specialist agents 窶・catalog (browse & cart), checkout (shipping address), and order summary 窶・which coordinate the full purchase flow through **shared session state**, ending in an Amazon-style order summary. Runs entirely on Ollama Cloud (`gpt-oss:120b`) via LiteLLM.

**Highlights**

- ､・4-agent hierarchy 窶・`ecommerce_agent` (root) 竊・`catalog_agent` 竊・`checkout_agent` 竊・`order_summary_agent` with `transfer_to_agent` delegation
- 柏 Workflow gating 窶・checkout is blocked until user profile (name/email/mobile) is saved to session state
- 嚮 Session state as the data bus 窶・tools write `tool_context.state`; downstream agents read `{item} {quantity} {price} {shipping_address}` template variables
- 屏・・Function tools 窶・`save_user_info`, `save_cart`, `save_shipping_address` persist workflow data across agents
- ｧ Tool-calling on open models 窶・LiteLLM `openai/` provider against Ollama Cloud (native `format: json` breaks tool calling)
- 剥 Full observability 窶・`adk web` dev UI with event traces, agent-transfer graph, and live state inspector
- 当 Self-contained interactive **user guide** (`userguide.html`) in plain language

> 塘 **Full docs, setup guide, and architecture:** [`Agentic-AI-Ecommerce-Orchestrator/README.md`](./Agentic-AI-Ecommerce-Orchestrator/README.md) ﾂｷ
> 答 **Interactive user guide (HTML):** [`Agentic-AI-Ecommerce-Orchestrator/userguide.html`](./Agentic-AI-Ecommerce-Orchestrator/userguide.html)

| Order summary (end-to-end result) | Session state 窶・the data bus |
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
## 亮・・Roadmap

- [x] 5・鞘Ε Knowledge Graph Builder 窶・ADK agents + Neo4j + natural language Q&A 竊・**[KnowledgegraphUIapp](./KnowledgegraphUIapp/)**
- [x] 6・鞘Ε Model Evaluation Harness 窶・automated LLM benchmarking & regression testing 竊・**[rag-evaluation-harness](./rag-evaluation-harness/)**
- [x] 7・鞘Ε Classic NLP / ML Sentiment Analysis 窶・end-to-end text classification teaching notebook 竊・**[NLP_MachineLearning_SentimentAnalysis](./NLP_MachineLearning_SentimentAnalysis/)**
- [x] 8・鞘Ε Multi-Agent Workflow Orchestrator 窶・ADK-style agent collaboration patterns 竊・**[Agentic-AI-Ecommerce-Orchestrator](./Agentic-AI-Ecommerce-Orchestrator/)**

## 屏・・Common Tech

| Layer | Tools |
|-------|-------|
| LLM Orchestration | LangChain (LCEL), LangGraph, Google ADK, NVIDIA NeMo Guardrails |
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
