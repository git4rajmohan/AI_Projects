# NeMo Guardrails Classroom — Project Summary

## What This Is

A **Streamlit teaching app** for NeMo Guardrails. Students bring their own Groq API key (BYOK) and run 7 progressive experiments, each adding one more safety layer on top of the previous. The domain is an **Enterprise IT Assistant** specialising in Kubernetes, Intel hardware, and enterprise networking — guardrails protect it from abuse.

## Folder Structure

```
guardrails/
├── app.py              ← Main Streamlit app (UI, tabs, chat, BYOK, model selection)
├── colang_defs.py      ← All YAML config strings + Colang rule strings (pure constants)
├── actions.py          ← NeMo @action decorated Python functions (PII, urgency, sanitizer)
├── diagrams.py         ← Graphviz DOT strings per experiment (rendered via st.graphviz_chart)
├── rail_configs.py     ← Builds LLMRails instance for each experiment number
├── guardrails.ipynb    ← Original Jupyter notebook (source of truth for experiments)
├── README.md           ← Full theory reference (Colang, rail types, flow diagrams)
├── requirements.txt    ← Python dependencies
└── .gitignore
```

## The 7 Experiments

| # | Rail Type | What's Added | New Concept |
|---|---|---|---|
| 1 | None | Raw LLM, zero protection | The problem |
| 2 | Input Rail | Topic Guard — blocks off-topic questions | Colang DSL: `define user / define bot / define flow` |
| 3 | Input Rail | Jailbreak Shield | Semantic intent classification |
| 4 | Input Rail | Sensitive Topic Block | Multi-rail stacking |
| 5 | Input Rail | Dialog Rails — scripted greeting/farewell/help | Conversation flow control |
| 6 | Custom Action | PII Detector + Urgency Classifier | `@action` decorator, systematic input rails |
| 7 | Output Rail | Response Sanitizer | Post-LLM interception via `rails.output.flows` |

Experiments are **cumulative** — each one includes all rails from previous experiments plus one new concept.

## App UI Structure

```
Sidebar
├── Groq Key — Chatbot LLM      (for Exp 1, model: llama-3.1-8b-instant)
├── Groq Key — Guardrail LLM    (for Exp 2–7, model: llama-3.3-70b-versatile)
├── Model selectors              (dropdown per LLM, 6 Groq models available)
└── Logfire Token (optional)     (Pydantic Logfire tracing)

Main Area (st.tabs)
├── 🔴 Baseline          → render_experiment(1)
├── 📥 Input Rails       → st.radio sub-nav → render_experiment(2/3/4/5)
├── ⚙️ Custom Actions    → render_experiment(6)
└── 📤 Output Rails      → render_experiment(7)

Each experiment renders:
├── Description + new concept
├── Graphviz flow diagram (left) | Rails active + Colang snippet (right)
├── Categorised example prompts (list with ▶ Send buttons)
└── st.chat_message history + st.chat_input
```

## Key Technical Decisions

### BYOK
- Groq keys are entered as `type="password"` text inputs in the sidebar
- Keys go directly to `ChatGroq(api_key=...)` — never stored or logged
- Two keys: one for the chatbot LLM, one for the guardrail LLM (can be the same key)
- Logfire token is optional — only used if entered

### LLM Caching
`@st.cache_resource` caches `ChatGroq` and `LLMRails` objects keyed by `(model_id, api_key)` and `(exp_num, guard_key, guard_model)`. Changing model or key mid-session automatically creates a fresh instance.

### Async Fix (important)
`nest_asyncio` is NOT used. It was breaking Streamlit's anyio-based ASGI server with `NoEventLoopError` when patched at module level.

Instead, all NeMo calls run inside a `ThreadPoolExecutor` worker thread:
```python
_executor = ThreadPoolExecutor(max_workers=2)

def _run_in_thread(fn, *args, **kwargs):
    return _executor.submit(fn, *args, **kwargs).result(timeout=120)
```
Worker threads have no running event loop, so NeMo's internal `asyncio.run()` works cleanly.

### Modular Design
- `colang_defs.py` — pure string constants, no logic
- `actions.py` — pure Python action functions, no Streamlit imports
- `diagrams.py` — pure DOT strings, no logic
- `rail_configs.py` — `build_rails(exp_num, guard_llm)` is the only public function
- `app.py` — all UI logic, imports from the above modules

`render_experiment(exp_num)` is a single reusable function that renders the full UI for any experiment number.

### Colang Stacking
```python
# rail_configs.py
_COLANG_MAP = {
    2: COLANG_TOPIC_GUARD,
    3: COLANG_TOPIC_GUARD + COLANG_JAILBREAK,
    4: COLANG_TOPIC_GUARD + COLANG_JAILBREAK + COLANG_SENSITIVE,
    5: COLANG_EXP5_FULL,                           # all four stacked
    6: COLANG_EXP5_FULL + COLANG_ACTIONS,
    7: COLANG_EXP5_FULL + COLANG_OUTPUT_RAIL,
}
```
Exp 6 and 7 both build on the full Exp 5 stack but diverge from each other (Exp 6 adds custom input actions, Exp 7 adds output rail — they don't stack on each other).

## Groq Models Available (verified June 2026)

| Model ID | Notes |
|---|---|
| `llama-3.3-70b-versatile` | Default guardrail LLM — best for intent classification |
| `llama-3.1-8b-instant` | Default chatbot LLM — fast, lightweight |
| `openai/gpt-oss-120b` | Advanced reasoning |
| `openai/gpt-oss-20b` | Fast, cost-effective |
| `meta-llama/llama-4-scout-17b-16e-instruct` | Preview |
| `qwen/qwen3-32b` | Preview |

## How to Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Requires Python 3.9+ (tested on 3.14 with the thread pool async fix).
No `.env` file needed — keys are entered in the UI.
