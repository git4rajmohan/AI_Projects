# 🛡️ AI-Safe Support Ticket Classifier

**Production-grade AI ticket triage with a live pipeline visualizer — safety rails (PII redaction, prompt-injection guard, validation, fallback) wrapped around an LLM classifier, with every node's output inspectable in the UI.**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C?logo=langgraph&logoColor=white)
![Ollama](https://img.shields.io/badge/LLM-Ollama_Cloud_gpt--oss:120b-654438?logo=ollama&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-8%2F8_passing-4ade80)
![License](https://img.shields.io/badge/License-MIT-blue)

---

## 📌 Overview

Most LLM demos stop at "prompt in, answer out." This project builds the **missing production layer**: a
LangGraph pipeline where every stage is a hard, auditable boundary — personal data is scrubbed before the
model sees it, a dedicated guard model vetoes manipulation attempts, structured output is schema-validated,
failures route to a safe fallback, and **every node's input/output is inspectable in the browser**.

The centerpiece is a **workflow visualization**: the 6-node pipeline renders as a live strip where each node
lights up **green** (completed), **red** (failed), **grey** (skipped), with a **yellow pulse** during replay —
and clicking any node opens a detail drawer showing exactly what that stage saw and produced.

## ✨ Features

| | Feature | What it does |
|--|---------|--------------|
| 🧠 | **LLM classification** | Categorizes tickets into 7 issue types, assigns one of 5 teams, priority (low→critical), sentiment (positive→angry), confidence score + reasoning |
| 🛡️ | **PII redaction** | Regex engine strips emails, phone numbers, and card numbers *before* any LLM call |
| 🚨 | **Prompt-injection guard** | Dedicated LLM judge (JSON-mode structured verdict) blocks "ignore your instructions" attacks; **fails safe** — a guard error blocks the input |
| ✅ | **Output validation** | Pydantic schema + business rules (confidence range, low-confidence ⇒ human review) |
| 🔁 | **Fallback with retry** | Tenacity-backed retries, then a conservative `SAFE_CLASSIFICATION` so a ticket is never lost |
| 📊 | **Live workflow visualizer** | Color-coded pipeline strip with per-node durations, replay animation, SVG edges |
| 🔍 | **Node detail inspector** | Click any node → slide-over drawer: redacted text, PII chips, guard verdict, full classification, validation errors, cost breakdown, raw JSON |
| ⚠️ | **Human-review flagging** | Low-confidence or fallback results are stamped "Flagged for human review" |
| 💰 | **Cost tracking** | Per-call token counts + USD cost, session roll-up on shutdown |
| 🏷️ | **Prompt versioning** | Versioned prompt registry (`GET /prompts`); every result is stamped with the prompt version used |
| 🌐 | **Dual-channel input** | `web_form` and `email` channels |
| 📖 | **Two-tier user guide** | In-app docs: a non-technical explainer tab and a technical architecture tab (`/userguide.html`) |

## 🖼️ Screenshots

### Green path — clean classification with PII redaction
![Green path](docs/images/01_green_path.png)

### Red path — injection attack blocked (classify/validate skipped)
![Injection blocked](docs/images/02_injection_blocked.png)

### Node inspector — PII redact drawer
![Node drawer](docs/images/03_node_drawer.png)

### Built-in two-tier user guide
![User guide](docs/images/04_userguide.png)

## 🏗️ Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              FastAPI (main.py)              │
                    │   POST /classify   GET /prompts  /docs      │
                    │         serves demo_ui/ at "/"              │
                    └────────────────────┬────────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────────┐
                    │        LangGraph StateGraph (graph.py)      │
                    │       run_pipeline_traced(...)              │
                    │   graph.stream(stream_mode="updates")       │
                    └────────────────────┬────────────────────────┘
                                         │
      START ──► pii_redact ──► injection_check ──► classify ──► validate ──┬──► cost_log ──► END
                                                    │          │           ▲
                                                    │          │ fail      │
                                                    │          ▼           │
                                                    │        fallback ─────┘
                                                    │   (validation fail only —
                                                    │    injection block routes
                                                    │    straight to cost_log)
                                                    │
                                                    ▼
                                          production_modules/
```

**Each node delegates to an isolated production module:**

| Node | Module | Mechanism |
|------|--------|-----------|
| `pii_redact` | `pii_redaction.py` | Regex: EMAIL / PHONE / CREDIT_CARD (13–19 digits) → labelled placeholders |
| `injection_check` | `prompt_injection.py` | LLM-as-a-judge, JSON-mode `InjectionJudgement`, fails safe to block |
| `classify` | `structured_output.py` | `ChatOpenAI` JSON mode, schema-escaped prompt, robust JSON extraction |
| `validate` | `validate_response.py` | Pydantic `TicketClassification` + business rules |
| `fallback` | `fallback_retry.py` | Tenacity retry → `SAFE_CLASSIFICATION` (human review, confidence 0) |
| `cost_log` | `cost_calculator.py` | Token counting + per-1K pricing → `CostInfo` |

### The trace contract

`POST /classify` returns the classification **plus a per-node `trace[]`** — this is what powers the UI:

```json
{
  "issue_category": "delivery_issue",
  "...": "…final fields…",
  "trace": [
    {
      "node": "injection_check",
      "label": "Injection Check",
      "status": "success | failed | skipped",
      "duration_ms": 1728,
      "output": { "is_safe": true, "detected_pattern": null }
    }
  ]
}
```

Status derivation: injection-blocked ⇒ `injection_check` **failed** and `classify`/`validate` **skipped**;
validation fail ⇒ `validate` **failed** and `fallback` runs; nodes that never execute (fallback on clean runs)
are synthesized as **skipped** with `output: null`.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- An [Ollama Cloud API key](https://ollama.com/settings/keys) (or any OpenAI-compatible endpoint)

### Setup

```bash
# 1. Clone
git clone https://github.com/git4rajmohan/AI_Projects.git
cd AI_Projects/AI-Safe-Support-Ticket-Classifier

# 2. Create venv + install
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt

# 3. Configure credentials — copy the example and add YOUR key
copy .env.example .env            # (cp on Linux/macOS)
#   → edit .env and set OLLAMA_API_KEY

# 4. Run
.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

Open **http://localhost:8000** — pick a sample ticket and classify it.

- **Interactive API docs:** http://localhost:8000/docs
- **User guide:** http://localhost:8000/userguide.html

### Run the tests

```bash
python -m pytest tests/ -v     # 8 tests — LLM calls mocked, runs offline
```

## 🎮 Demo script (3 clicks, 3 pipeline behaviors)

| Click | Sample | What you'll see |
|-------|--------|-----------------|
| 1 | 📦 Delayed Delivery | All nodes **green**, PII chips in the drawer, human-review logic |
| 2 | 🚨 Injection Attack | `injection_check` turns **red**, `classify`/`validate` **grey-skipped**, 🚫 banner |
| 3 | 🤔 Vague Complaint | Low confidence → ⚠ "Flagged for human review" |

Plus 📞 **All PII Types** (phone + card + email redacted simultaneously) and 💳/🔐 for payment/account paths.

> **Note:** the `fallback` node stays grey in normal runs — it only executes when the LLM returns malformed
> output. That's the safety net working as designed, not a bug.

## 📁 Project Structure

```
AI-Safe-Support-Ticket-Classifier/
├── main.py                      # FastAPI app: /classify (+trace), /prompts, /health, static UI
├── graph.py                     # LangGraph pipeline + run_pipeline_traced() trace capture
├── schema.py                    # Pydantic enums + TicketClassification + TicketState
├── requirements.txt
├── .env.example                 # credential template (real .env is git-ignored)
├── production_modules/
│   ├── pii_redaction.py         # regex PII scrubber
│   ├── prompt_injection.py      # LLM-judge injection guard
│   ├── structured_output.py     # JSON-mode classifier (function-calling variant included)
│   ├── validate_response.py     # schema + business-rule validation
│   ├── fallback_retry.py        # tenacity retry + SAFE_CLASSIFICATION
│   ├── cost_calculator.py       # token/cost accounting + session tracker
│   ├── prompt_versioning.py     # versioned prompt registry
│   └── non_determinism.py       # temperature/seed experimentation demo
├── demo_ui/
│   ├── index.html               # single-file UI: workflow strip, drawer, replay animation
│   └── userguide.html           # two-tab docs (non-tech / tech)
├── tests/
│   └── test_classifier.py       # 8 offline tests (mocked LLM)
└── docs/
    └── images/                  # screenshots used in this README
```

## 🔒 Security & Privacy Notes

- **PII never reaches the LLM** — redaction happens in the first node, and the UI deliberately shows only the
  redacted copy (the original never leaves the server).
- **The injection guard fails closed** — if the guard model itself errors, the input is blocked, not passed through.
- **No credentials in the repo** — `.env` is git-ignored; `.env.example` is the template. Copy it and supply your
  own `OLLAMA_API_KEY`.

## 🛠️ Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Orchestration | **LangGraph** `StateGraph` | Conditional edges (validate → fallback), per-node streaming for tracing |
| API | **FastAPI** + Pydantic | Typed request/response models, lifespan hooks, auto `/docs` |
| LLM | **Ollama Cloud** — `gpt-oss:120b` | OpenAI-compatible endpoint via `langchain-openai` |
| Validation | **Pydantic v2** | Enum-constrained schema + custom business rules |
| Retries | **tenacity** | Exponential backoff on rate-limit/validation errors |
| Frontend | Vanilla HTML/CSS/JS | Zero build step; hand-rolled SVG edges; single-file deploy |
| Tests | **pytest** (8/8) | Fully offline via LLM mocking |

## 📄 License

MIT — see [LICENSE](LICENSE).

---

*Part of [AI_Projects](https://github.com/git4rajmohan/AI_Projects) — a curated showcase of AI/ML projects.*