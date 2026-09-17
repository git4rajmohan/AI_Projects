Languages: **English** | [日本語](README.ja.md)

---

# Research Voice Agent — From a One-Line Prompt to a Finished Podcast

A three-mode voice-AI pipeline: give it a prompt, a meeting transcript, or an audio recording,
and a small team of AI agents researches, writes the report, turns it into a conversational
script, and speaks it into an MP3 — with every tool call streamed live into the browser.

> Google ADK · Ollama Cloud (`gpt-oss:120b` via an embedded OpenAI→Ollama proxy) · FastAPI ·
> ddgs · yfinance · edge-tts · faster-whisper

## What This Project Demonstrates

- **Multi-agent orchestration on Google ADK** — a producer agent (research/tools) delegating to a
  podcaster agent via `AgentTool`: a sub-agent made callable like a function
- **Tool-grounded research** — `ddgs` web search fenced to a **domain whitelist enforced by ADK
  callbacks** (the model cannot bypass it), a freshness window on every query, and live stock
  context via `yfinance`
- **Speech pipeline** — per-host neural voices with edge-tts (chunked stream → concatenated MP3)
  and local transcription with faster-whisper in an isolated subprocess
- **Callbacks as the single source of UI truth** — the 10-step progress stepper advances only when
  the agent *actually calls a tool*, never on string-matched output
- **One model, many roles** — `gpt-oss:120b` plays researcher, writer, scriptwriter and audio
  specialist; specialization lives in instructions, tools and callbacks, not fine-tunes

## Why This Project Exists

Demonstrates a full multimodal/voice AI pipeline — research, script generation and speech
synthesis — rather than text-only LLM output. Producing a podcast the traditional way means
research tabs, a notes doc, a script draft, an audio editor and a microphone; this collapses the
whole production pipeline into one Start button, with the run visible step by step.

## The Three Modes

| Mode | Input | Output files | Steps |
|---|---|---|---|
| **AI News** | a text prompt | `artifacts/news/ai_research_report.md` + `ai_today_podcast.mp3` | 10 |
| **Meeting Recap** | pasted transcript or `.txt/.md/.vtt/.srt/.docx` file | `artifacts/recap/meeting_recap.md` + `meeting_recap.mp3` | 9 |
| **Audio Summary** | audio recording upload (mp3/wav/m4a/…) | `artifacts/summaries/audio_summary.md` + raw `transcript_*.txt` — **deliberately no podcast** | 4 |

- **AI News** searches whitelisted news sites, enriches stories with live stock data, writes a
  structured report (with an auditable *Data Sourcing Notes* section), then records the episode
- **Meeting Recap** extracts Key Decisions, Discussion Summary, an Action-Items table and Open
  Questions — with a faithfulness rule: only what's in the transcript; missing details become
  "Not specified", never invented
- **Audio Summary** transcribes locally (nothing leaves the machine except the final summary
  request) and writes a summary with timestamps; progress streams live from the transcriber
  subprocess (hard 900 s timeout)

Nothing goes stale: before every run the previous artifacts for that mode are archived to
`_old_<timestamp>` copies.

## Architecture

```text
Browser (single-page UI, served by FastAPI)
   polls /api/status every 1.5 s · stepper · live log · report viewer · audio player
        ↓
podcast_ui.py — FastAPI + uvicorn on 127.0.0.1:8000
   REST endpoints · config.json persistence · artifact archiving (_old_*)
   lock-guarded STATE · one worker thread per run · 409 if busy
        ↓  imports engine as a module (same process)
lesson6_podcast_agent.py — ADK agent engine
   producer Agent (preset-built, 4 tools, guardrail callbacks)
   podcaster Agent reachable through AgentTool
   embedded OpenAI→Ollama proxy (FastAPI on 127.0.0.1:11435, daemon thread)
        ↓                              ↓                        ↓
   ddgs (whitelist + freshness)   yfinance (stock context)   edge-tts (MP3 per host)
                                   audio path only → faster-whisper in _transcribe_sub.py subprocess
```

**The two agents, in code** — the producer is rebuilt per run from the active topic preset (goal,
scope, acknowledgment, financial-steps variant, host directives); the podcaster is a specialist
with a single tool:

```python
root_agent = Agent(
    name="ai_news_researcher", model=LiteLlm(model=OLLAMA_MODEL),  # openai/gpt-oss:120b
    instruction=root_instruction(...),
    tools=[web_search, get_financial_context, save_news_to_markdown,
           AgentTool(agent=podcaster_agent)],            # sub-agent as a callable tool
    before_tool_callback=[filter_news_sources_callback, enforce_data_freshness_callback],
    after_tool_callback=[inject_process_log_after_search],
)
```

Why no `output_schema`? ADK **disables tool use** when an output schema is set — fatal for a
workflow that lives on tool calls. The Pydantic schemas (`AINewsReport`, `MeetingRecap`,
`ActionItem`, `NewsStory`) are kept as structure guidance in the instructions instead.

## Workflow (news run, 10 steps)

1. **Acknowledge** — the producer confirms the goal (one of only two user-facing messages)
2. **Search news** — `web_search`, results filtered to the whitelist + freshness window by callbacks
3–4. **Extract tickers & fetch financials** — `get_financial_context` via yfinance; missing data
   becomes "Not Available", the run never halts
5–7. **Structure & save the report** — `save_news_to_markdown` writes
   `ai_research_report.md`; the Report panel updates the moment the file lands
8. **Write the script** — `Joe: … / Jane: …` lines matching the configured host names, count and personas
9. **Generate audio** — producer hands the script to the podcaster agent (AgentTool delegation);
   `generate_podcast_audio` regex-parses every `Speaker:` line, synthesizes each with that host's
   edge-tts voice, and concatenates the MP3 chunks into one episode
10. **Confirm done**

The stepper pills are driven by ADK tool callbacks — grey = waiting, amber = running, green =
done, red = failed. A live log shows every tool call, every filtered domain, transcription
progress percentages.

**Why an auto-continue loop exists:** Ollama chat models end their turn after a text-only message
and won't emit a tool call in the same response — the worker nudges the agent with "continue"
until the target artifact exists, bounded by `max_auto_continue` (default 10) so a stuck run fails
cleanly instead of hanging.

## Guardrails (ADK callbacks — enforced, not trusted)

| Callback | Enforcement |
|---|---|
| `filter_news_sources_callback` (before every tool) | Rewrites queries to the whitelist; any non-whitelisted-domain result is dropped before the model sees it |
| `enforce_data_freshness_callback` (before every tool) | Forces the freshness window (`week` default) onto every search |
| `inject_process_log_after_search` (after `web_search`) | Attaches the filtering log to the tool result — every report carries a *Data Sourcing Notes* section the user can audit |
| `ui_step_tracker_before/_after` (podcast_ui.py) | Map tool names to workflow steps; the UI can't lie about progress |

Missing tickers degrade to "Not Available"; missing recap fields to "Not specified" — the run
always delivers its artifacts rather than dying mid-flight.

## Technology Stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | Vanilla HTML/CSS/JS (embedded in the server file) | stepper, live log, report viewer, audio player, config panel |
| API server | FastAPI + uvicorn on 127.0.0.1:8000 (`podcast_ui.py`) | REST endpoints, run orchestration, config persistence |
| Agent framework | Google ADK (`google-adk==1.22.1`, pinned) | Runner, sessions, function tools, `AgentTool` delegation, callbacks |
| LLM | Ollama Cloud — `gpt-oss:120b` via LiteLLM | reasoning, research, reports, scripts, summaries |
| Format bridge | Embedded OpenAI→Ollama proxy (FastAPI on 127.0.0.1:11435) | translates OpenAI-style chat/tool calls to Ollama's native API |
| Web search | ddgs (DuckDuckGo) | fresh news, whitelist + freshness enforced by callbacks |
| Financial data | yfinance | stock context for mentioned tickers (skipped on non-market presets) |
| TTS | edge-tts (Microsoft neural voices) | per-host voices, MP3 chunks concatenated |
| STT | faster-whisper in an isolated subprocess (`_transcribe_sub.py`) | local transcription, JSON progress lines, 900 s hard cap |
| Config | `config.json` + python-dotenv | UI settings persistence; API key from `.env` |

## Customization

- **12 languages** — English, Japanese, Chinese, Tamil, Hindi, Spanish, French, German, Korean,
  Portuguese, Arabic, Russian; the whole run (report, script, voices) follows the setting, with
  hosts remapped to native voices
- **1–4 hosts** — each with name, edge-tts voice and persona; instant *Preview host* without a run
- **5 topic presets** — AI + market news (default), Tech industry, Research/academic,
  Entertainment · India, Custom; each swaps the prompt prefill, domain whitelist, search region
  and the agent's displayed name/step labels (non-market presets skip financial steps automatically)

## How to Run

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # then paste your key from https://ollama.com/settings/keys

.venv\Scripts\python.exe podcast_ui.py
# → http://127.0.0.1:8000  (the embedded proxy on :11435 starts automatically)
```

Pick a tab, give an input, press **▶ Start**. News: type a prompt. Recap: paste a transcript or
load a file. Audio summary: upload a recording in the Meeting Recap tab. First transcription is
slower once (the whisper model downloads once and is pre-warmed at startup).

**Full guide:** [`userguide.html`](./userguide.html) — 4-tab walkthrough (pitch, non-technical,
technical, glossary) with the message-sequence trace of a full news run.

## API Surface (podcast_ui.py)

`GET /` (single-page UI) · `GET/POST /api/config` · `POST /api/run` (`409` if a run is active) ·
`POST /api/stop` · `GET /api/status` · `GET /api/steps_config` · `GET /api/presets` ·
`GET /api/languages` · `GET /api/report?mode=` · `GET /api/audio?mode=&download=` ·
`POST /api/upload?filename=` · `GET /api/voice_preview`

## Key AI Engineering Concepts

- Sub-agent as a tool (`AgentTool`), not a conversational hand-off — audio generation is just
  another step in one workflow
- Callback-enforced guardrails (domain whitelist, freshness) the model cannot bypass
- Embedded OpenAI→Ollama format-translation proxy (tool-call shapes, array content, model prefix)
- Async-in-async containment: edge-tts synthesis runs on a dedicated thread with its own event
  loop; whisper runs in a subprocess — keeping ADK's running loop untouched
- Thread-per-run with a single-flight lock; stale "running" state self-heals

## Safety / Reliability

- Search is fenced to whitelisted domains by a **before-tool callback**, not by trust
- Every stock lookup goes through the yfinance tool rather than the model's memory
- Faithfulness rule in recap mode: no invented quotes or decisions; missing details are "Not specified"
- Audio never leaves the machine — transcription runs locally; only text requests go to the cloud LLM
- One run at a time (`409` if busy); transcription subprocess has a hard 900 s cap

## Testing / Evaluation

*Not documented in the current repository* — the project ships no automated test suite; the
userguide's verification steps (watch the stepper advance only when tools fire; artifacts land
under `artifacts/<mode>/`) are the manual check.

## How This Project Differs

A voice/multimodal pipeline where **agents plan and tools act**: research is fenced by callbacks,
speech is real (per-host neural voices), and the entire run streams into the browser. Unlike a
chatbot that returns text, the output here is a finished report *and* a playable MP3 — produced by
two cooperating ADK agents on one open-weights model.

## AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation
decisions, testing, debugging and validation were reviewed and refined during development.