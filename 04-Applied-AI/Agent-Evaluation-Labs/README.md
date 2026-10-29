Languages: **English** | [日本語](README.ja.md)

# Agent Evaluation Labs — LLM Agent Observability & Evaluation with Arize Phoenix

**From a traced agent run to graded evidence to A/B prompt comparison.**

[Portfolio](../../README.md) | [User guide](Userguide.html)

Agent Evaluation Labs builds a sales-data analyst agent (router + 3 tools) whose every LLM call, tool call and SQL execution is traced to Arize Phoenix, then grades the recorded evidence with four evaluation labs — all driven from one Streamlit dashboard. The evaluators are observers: they never change how the agent runs. Trace first, judge the recorded spans, compare before/after, then fix the weakest component.

## Why this project exists

A raw LLM agent looks smart in a demo and fails silently in real use. Did it pick the right tool? Is the SQL it wrote even relevant to the question? Is the answer clear — or merely plausible? Did a prompt change quietly regress what used to work? Without instrumentation you are guessing; with it, you are doing **evaluation-driven development**. This project is the instrumentation half of that practice — the companion to the portfolio's RAG Evaluation Harness, which evaluates RAG systems rather than tool-calling agents.

**The signal:** the same instrumentation that shows you the agent's path in development powers its regression tests later.

## What it demonstrates

- **Tracing-first architecture** — the agent run is traced to Phoenix (project `evaluating-agent`) under an `AgentRun` root span: `AgentRun → router_call → tool spans → nested LLM spans`, auto-instrumented by OpenInference. Labs query those spans afterwards; evaluation never changes execution.
- **Full message trajectory as the evaluation target** — `run_agent()` appends every message to `messages` in place; `process_messages()` summarizes it into `{tool_calls, tool_responses, final_output, path_length}` matched by `tool_call_id`. The trajectory is collected in place, not re-derived.
- **Four labs on one dashboard** — Lab 5 (tracing demo: 2 questions + span trees), Lab 7 (router & skill evals: LLM judges on real recorded tool calls, SQL and answers + a code eval that `exec()`s generated chart code), Lab 9 (convergence eval: 17 paraphrases of one question scored on path efficiency via a Phoenix experiment), Lab 11 (overall eval: 5 evaluators over 7 questions, then an A/B rerun with a modified SQL prompt). A "run all" mode chains the non-interactive labs.
- **LLM-as-judge plumbing without trace pollution** — `run_judge()` uses raw HTTP + JSON mode (`response_format: json_object`) and is wrapped in `suppress_tracing()`, so judge calls never appear as spans in the very traces being judged (the `phoenix.evals` API was removed in Phoenix 20.x; raw HTTP also keeps judges un-instrumented). Judge label, score and full reasoning are logged back to Phoenix as span annotations.
- **Subprocess protocol keeps the UI generic** — `app.py` only launches `python eval.py <lab>` and streams stdout, parsing two conventions: `Q:/A:` answer markers and `__EVAL_UI__ {json}` score lines. `eval.py` changes freely as long as it keeps speaking these two formats.
- **Honest failure semantics on screen** — "Run completed" means execution finished, not that every check passed; judge errors fall back to caller-chosen defaults; Lab 11 treats a missing SQL/chart tool response as passing that check (a documented scope limit, not a success); convergence measures efficiency only.
- **Recorded evidence** — `record_test.py` drives each lab end-to-end in headless Chromium (Playwright, video capture) and asserts the expected UI artifacts per lab; verdicts, videos and screenshots ship in [test_videos/](test_videos/) with a visual [report](test_videos/report.html).

## Architecture

```text
Streamlit app.py (launcher + renderer)
  -> subprocess: python eval.py <lab>
       -> utils.py: run_agent()
            router LLM -> tool call? -> lookup_sales_data (SQL -> DuckDB over parquet)
                                     -> analyze_sales_data (LLM interprets)
                                     -> generate_visualization (JSON-mode chart config
                                        -> LLM writes Python chart code)
            every call = Phoenix span (OpenInference auto-instrumentation)
       -> eval.py labs query spans / run Phoenix experiments
       -> LLM judges (raw HTTP, JSON mode, suppress_tracing) grade recorded evidence
       -> scores logged back to Phoenix as span annotations
  <- stdout protocol: "Q:/A:" answers + __EVAL_UI__ score lines
Dashboard renders answers, per-check score table, judge reasoning, Phoenix links
```

The agent LLM and the judge LLM are the same configured Ollama Cloud model (default `gpt-oss:120b`); judge calls deliberately escape instrumentation.

**Stack:** Python · Streamlit · Arize Phoenix (local server, auto-started) · OpenInference/OpenTelemetry · OpenAI SDK (Ollama Cloud, OpenAI-compatible) · DuckDB · Pydantic · Pandas · matplotlib/seaborn · Playwright (test recorder) · Streamlit AppTest (unit checks)

## Run locally (Windows PowerShell)

From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and paste your Ollama API key (create one at https://ollama.com/settings/keys)
python -m streamlit run app.py
# -> http://localhost:8501  (Phoenix starts itself at http://localhost:6006 on first use)
```

No key, no agent — the app tells you exactly where to create one. Runs take minutes because each agent turn involves multiple real LLM calls; the dashboard streams progress live. Tip: run Lab 5 first — seeing the span tree of a single question is the fastest way to understand what the other labs judge.

### What each lab does

| Lab | Mechanism | Evaluators | What you get |
|---|---|---|---|
| 5 · Tracing demo | 2 questions under an `AgentRun` root span | — | 2 answers + span trees in Phoenix |
| 7 · Router & skill evals | Span queries + LLM judges + code eval | Tool Calling (LLM) · SQL Gen (LLM) · Clarity (LLM) · Runnable Code (code) | Score per check + graded examples with judge reasoning |
| 9 · Convergence eval | Phoenix experiment over 17 paraphrases | Convergence (code): shortest observed path ÷ this path | Convergence score, dataset reused on reruns |
| 11 · Overall eval | Phoenix experiments ×2 | Tool selection (LLM) · SQL result match (code, digit comparison) · Clarity (LLM) · Entity correctness (LLM) · Chart code runnable (code, `exec`) | Two compared experiment runs ("Overall Experiment" / "v2") in Phoenix |

There is also an interactive Lab 3 (chat REPL; chart code from answers is executed and saved) reachable via `python eval.py 3` — excluded from the dashboard's run-all chain.

## Recorded verification results

Every lab was verified end-to-end by [record_test.py](record_test.py) driving the app in headless Chromium: it selects the lab, clicks run, polls for "Run finished", asserts the expected UI artifacts, and screenshots the app and Phoenix. The verdicts below are from that recorded run (2026-10-29); raw evidence is [test_videos/results.json](test_videos/results.json) and the full [visual report](test_videos/report.html) with per-lab videos.

| Lab | Verdict | Runtime | Assertions that passed |
|---|---|---|---|
| 5 Tracing | ✅ pass | 1.9 min | answers metric + Traces section with span trees |
| 7 Router/Skills | ✅ pass | 12.5 min | evaluation scores + "How this was tested" graded examples |
| 9 Convergence | ✅ pass | 1.9 min | score table + convergence details + technical logs |
| 11 Overall | ✅ pass | 4.5 min | score table (both runs) + evaluator details + technical logs |

Unit-level checks live in `test_app.py` (Streamlit AppTest over mocked subprocesses: answer rendering, `__EVAL_UI__` score table, per-lab selection guides, failure path, session-reset behavior). Run with `python -m unittest test_app`. Note: the suite passes with no Phoenix server already listening; with a live Phoenix the auto-start readiness check can outrun AppTest's 3-second widget timeout.

## Limits and scope notes (shown in the app too)

- Lab 7 scores cover all matching stored project spans, not just the latest run.
- Convergence measures path efficiency only; a short path does not prove a correct answer.
- Lab 11's "missing tool response = pass" is a scope limit — inspect tool selection as well.
- LLM judges can mislabel; every grade ships with its full reasoning so you can inspect it. Code evals are deterministic.
- SQL result matching compares digit concatenations, not full result semantics.

## Credentials and safety

- Only a placeholder-key template is published (`.env.example`); the real `.env` is git-ignored and excluded from this copy. Config: `OLLAMA_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `PHOENIX_ENDPOINT`.
- The judge and the agent share one model/endpoint by design; swap `OLLAMA_MODEL` to split them.
- The agent executes LLM-generated SQL (read-only DuckDB over the bundled parquet) and LLM-generated chart code (matplotlib, Agg backend). Review generated chart code before reusing that pattern elsewhere.

## Project layout

| Path | Purpose |
|---|---|
| [app.py](app.py) | Streamlit launcher/renderer: runs `eval.py <lab>`, parses output, renders score tables |
| [eval.py](eval.py) | All labs: span-query evals, experiments, judges, dataset/reuse plumbing, A/B prompt swap |
| [utils.py](utils.py) | The agent: router loop, 3 tools, Phoenix setup, trajectory summarizer |
| [test_app.py](test_app.py) | Streamlit AppTest unit checks over mocked subprocesses |
| [record_test.py](record_test.py) | Playwright driver: per-lab video capture + assertions + verdicts |
| [data/](data/) | Store sales dataset (price elasticity + promotions parquet) read by DuckDB |
| [test_videos/](test_videos/) | Recorded lab runs: videos, screenshots, results.json, report.html |
| [Userguide.html](Userguide.html) | Full illustrated guide (elevator pitch, non-technical and technical tabs); download and open in a browser |