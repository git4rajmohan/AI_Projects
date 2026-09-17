"""
Lesson 6 - Multi-agent orchestration (single-file version, Ollama Cloud)
========================================================================

Converted from Lesson_6.ipynb (DeepLearning.AI ADK course).

What it does
------------
A two-agent Google ADK system that:
  1. Searches the web (DuckDuckGo) for the latest AI news about
     NASDAQ-listed US companies (whitelisted tech-news domains only).
  2. Enriches stories with live stock prices (yfinance).
  3. Compiles a structured AI research report and saves it as
     `ai_research_report.md`.
  4. Writes a configurable multi-host podcast script (Joe + Jane by default)
     and converts it to an MP3 audio file `ai_today_podcast.mp3` using
     edge-tts (one neural voice per host).
  5. Opens the audio in your default player.

How to run
----------
    # 1. Put your Ollama cloud API key in .env (OLLAMA_API_KEY=...)
    # 2. Run:
    .venv\\Scripts\\python.exe lesson6_podcast_agent.py

Architecture
------------
    root_agent (producer, LiteLlm -> Ollama cloud via local proxy)
      |-- tools: web_search, get_financial_context, save_news_to_markdown
      |-- callbacks: whitelist domains, freshness, process-log injection
      '-- AgentTool -> podcaster_agent (delegates audio generation)
                        '-- tool: generate_podcast_audio (edge-tts)

The LLM runs on Ollama cloud (https://ollama.com/api/chat). Ollama's cloud
API uses its native format, not OpenAI format, so this file embeds a small
FastAPI proxy on 127.0.0.1:11435 that translates OpenAI <-> Ollama.
ADK talks OpenAI format (via LiteLlm); the proxy talks to Ollama cloud.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import sys
import threading
import time
import uuid
import wave  # noqa: F401  (kept from the lesson's wave helper; unused with edge-tts)
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Environment (.env must be loaded before anything reads env vars)
# ---------------------------------------------------------------------------
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# ===========================================================================
# SECTION 1 - Embedded Ollama-cloud proxy (OpenAI format <-> Ollama native)
# ===========================================================================
# Adapted from AI_GraphRAG/ollama_cloud_proxy.py. Ollama cloud only speaks its
# native format; ADK/LiteLLM speak OpenAI format. This proxy bridges them.

OLLAMA_CLOUD_HOST = os.getenv("OLLAMA_CLOUD_HOST", "https://ollama.com")
OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_API_KEY") or ""
PROXY_HOST = os.getenv("OLLAMA_PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("OLLAMA_PROXY_PORT", "11435"))

proxy_app = FastAPI(title="Ollama Cloud OpenAI Proxy")


def _post_json(url: str, payload: Dict[str, Any], api_key: str, retries: int = 5) -> Dict[str, Any]:
    """POST JSON to Ollama cloud with retry/backoff on 429/500/503."""
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(retries):
        req = requests.Request(
            "POST", url, data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        ).prepare()
        try:
            with requests.Session() as s:
                resp = s.send(req, timeout=300)
            if resp.status_code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))  # 2,4,8,16s backoff
                continue
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code,
                                    detail=f"Ollama cloud error: {resp.text[:500]}")
            return resp.json()
        except HTTPException:
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise


def _strip_model_prefix(model: str) -> str:
    """Remove provider prefixes like 'openai/' from the model name."""
    for prefix in ("openai/", "ollama/", "hosted_vllm/"):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def _translate_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI messages -> Ollama native messages.

    Differences handled:
    - tool_calls: OpenAI has id/type; Ollama does not.
    - arguments: OpenAI sends a JSON string; Ollama expects a dict.
    - tool-result messages: Ollama uses role+content only (no tool_call_id).
    - array content: ADK sometimes sends content as [{type:text,...}]; Ollama
      wants a plain string -> flatten.
    """
    translated = []
    for msg in messages:
        role = msg.get("role", "user")
        out: Dict[str, Any] = {"role": role}

        content = msg.get("content")
        if content is not None:
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(part["text"])
                    elif isinstance(part, str):
                        parts.append(part)
                out["content"] = "\n".join(parts)
            else:
                out["content"] = content

        if role == "assistant" and msg.get("tool_calls"):
            ollama_tc = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                ollama_tc.append({"function": {"name": fn.get("name", ""), "arguments": args}})
            out["tool_calls"] = ollama_tc

        if role == "tool":
            out = {"role": "tool", "content": msg.get("content", "")}

        translated.append(out)
    return translated


@proxy_app.post("/v1/chat/completions")
async def chat_completions(request: Dict[str, Any]):
    """OpenAI /v1/chat/completions -> Ollama /api/chat."""
    model = _strip_model_prefix(request.get("model", "gpt-oss:120b"))
    messages: List[Dict[str, Any]] = request.get("messages", [])
    tools = request.get("tools")
    tool_choice = request.get("tool_choice")

    ollama_payload: Dict[str, Any] = {
        "model": model,
        "messages": _translate_messages(messages),
        "stream": False,
    }

    for src, dst in [("temperature", "temperature"), ("top_p", "top_p"),
                     ("max_tokens", "num_predict"), ("stop", "stop"), ("seed", "seed")]:
        if request.get(src) is not None:
            ollama_payload[dst] = request[src]

    if tools:
        ollama_tools = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                fn = tool["function"]
                params = fn.get("parameters")
                if params is None:
                    params = {"type": "object", "properties": {}}
                elif isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except json.JSONDecodeError:
                        params = {"type": "object", "properties": {}}
                ollama_tools.append({"type": "function", "function": {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": params,
                }})
        ollama_payload["tools"] = ollama_tools
    if tool_choice:
        ollama_payload["tool_choice"] = tool_choice

    rf = request.get("response_format")
    if isinstance(rf, dict) and rf.get("type") == "json_object":
        ollama_payload["format"] = "json"

    result = _post_json(f"{OLLAMA_CLOUD_HOST}/api/chat", ollama_payload, OLLAMA_CLOUD_API_KEY)

    message = result.get("message", {})
    content = message.get("content", "")
    tool_calls = message.get("tool_calls")

    openai_message: Dict[str, Any] = {"role": message.get("role", "assistant")}
    if content:
        openai_message["content"] = content
    if tool_calls:
        openai_message["tool_calls"] = [
            {
                "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                "type": "function",
                "function": {
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": (
                        json.dumps(tc["function"]["arguments"])
                        if isinstance(tc.get("function", {}).get("arguments"), dict)
                        else tc.get("function", {}).get("arguments", "{}")
                    ),
                },
            }
            for tc in tool_calls
        ]

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": openai_message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {
            "prompt_tokens": result.get("prompt_eval_count", 0),
            "completion_tokens": result.get("eval_count", 0),
            "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
        },
    }


@proxy_app.get("/health")
async def health():
    return {"status": "ok", "upstream": OLLAMA_CLOUD_HOST}


def _is_proxy_up() -> bool:
    try:
        return requests.get(f"http://{PROXY_HOST}:{PROXY_PORT}/health", timeout=2).ok
    except Exception:
        return False


def ensure_proxy_running() -> None:
    """Start the embedded proxy in a daemon thread if not already running."""
    if _is_proxy_up():
        print(f"[proxy] already running on http://{PROXY_HOST}:{PROXY_PORT}")
        return
    thread = threading.Thread(
        target=lambda: uvicorn.run(proxy_app, host=PROXY_HOST, port=PROXY_PORT,
                                   log_level="warning"),
        daemon=True,
    )
    thread.start()
    for _ in range(50):  # wait up to ~5s
        if _is_proxy_up():
            break
        time.sleep(0.1)
    if _is_proxy_up():
        print(f"[proxy] started on http://{PROXY_HOST}:{PROXY_PORT}")
    else:
        print("[proxy] WARNING: proxy did not come up - LLM calls will fail")


# ===========================================================================
# SECTION 2 - Pydantic schemas (verbatim from the lesson)
# ===========================================================================
from pydantic import BaseModel, Field
from typing import List


class NewsStory(BaseModel):
    """A single news story with its context."""
    company: str = Field(description="Company name associated with the story (e.g., 'Nvidia', 'OpenAI'). Use 'N/A' if not applicable.")
    ticker: str = Field(description="Stock ticker for the company (e.g., 'NVDA'). Use 'N/A' if private or not found.")
    summary: str = Field(description="A brief, one-sentence summary of the news story.")
    why_it_matters: str = Field(description="A concise explanation of the story's significance or impact.")
    financial_context: str = Field(description="Current stock price and change, e.g., '$950.00 (+1.5%)'. Use 'No financial data' if not applicable.")
    source_domain: str = Field(description="The source domain of the news, e.g., 'techcrunch.com'.")
    process_log: str = Field(description="populate the `process_log` field in the schema with the `process_log` list from the `web_search` tool's output.")


class AINewsReport(BaseModel):
    """A structured report of the latest AI news."""
    title: str = Field(default="AI Research Report", description="The main title of the report.")
    report_summary: str = Field(description="A brief, high-level summary of the key findings in the report.")
    stories: List[NewsStory] = Field(description="A list of the individual news stories found.")


class ActionItem(BaseModel):
    """A single action item extracted from a meeting transcript."""
    task: str = Field(description="What needs to be done.")
    owner: str = Field(description="Person responsible for the task, or 'Unassigned'.")
    deadline: str = Field(description="Deadline or due date mentioned, or 'Not specified'.")


class MeetingRecap(BaseModel):
    """A structured recap of a meeting transcript."""
    title: str = Field(default="Meeting Recap", description="The main title of the recap.")
    meeting_date: str = Field(default="Not specified", description="Date of the meeting if known.")
    attendees: List[str] = Field(description="People who spoke or attended, best-effort from the transcript.")
    key_decisions: List[str] = Field(description="Decisions made in the meeting, one item per decision.")
    discussion_summary: str = Field(description="A concise narrative summary of the discussion and main arguments.")
    action_items: List[ActionItem] = Field(description="Action items with owner and deadline.")
    open_questions: List[str] = Field(default_factory=list, description="Unresolved questions or risks raised.")


# ===========================================================================
# SECTION 3 - Tools
# ===========================================================================
import yfinance as yf
from google.adk.tools import ToolContext


def web_search(query: str, max_results: int = 8) -> str:
    """Search the web (DuckDuckGo) and return formatted results.

    Returns a single string: one line per result, "title | url | snippet".
    (A plain-string return keeps the lesson's after-tool callback logic
    identical - it regex-extracts URLs from the response text.)
    """
    if max_results is None:
        max_results = SEARCH_MAX_RESULTS
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, region=SEARCH_REGION,
                                 timelimit=SEARCH_TIMELIMIT,
                                 max_results=max_results))
        if not raw:
            return "No results found for the query."
        lines = []
        for r in raw:
            title = r.get("title", "")
            url = r.get("href") or r.get("url") or ""
            body = r.get("body") or r.get("snippet") or ""
            lines.append(f"{title} | {url} | {body}")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {str(e)[:200]}"


def get_financial_context(tickers: List[str]) -> Dict[str, str]:
    """Fetches the current stock price and daily change for a list of stock tickers."""
    financial_data: Dict[str, str] = {}

    valid_tickers = [t.upper().strip() for t in tickers
                     if t and t.upper() not in ("N/A", "NA", "")]

    if not valid_tickers:
        return {t: "No financial data" for t in tickers}

    for ticker_symbol in valid_tickers:
        try:
            stock = yf.Ticker(ticker_symbol)
            info = stock.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            change_percent = info.get("regularMarketChangePercent")

            if price is not None and change_percent is not None:
                change_str = f"{change_percent * 100:+.2f}%"
                financial_data[ticker_symbol] = f"${price:.2f} ({change_str})"
            else:
                financial_data[ticker_symbol] = "Price data not available."
        except Exception:
            financial_data[ticker_symbol] = "Invalid Ticker or Data Error"

    return financial_data


# Output locations: everything the app generates lands in workspace
# folders instead of cluttering the root. Override with PODCAST_OUTPUT_DIR.
_BASE_DIR = pathlib.Path(__file__).resolve().parent
OUTPUT_DIR = pathlib.Path(os.getenv("PODCAST_OUTPUT_DIR", str(_BASE_DIR / "artifacts")))
TRANSCRIPTS_DIR = _BASE_DIR / "transcripts"
RECORDINGS_DIR = _BASE_DIR / "recordings"


def output_dir(mode: str = "") -> pathlib.Path:
    """Output folder for a mode: artifacts/<mode>, creating it if needed."""
    sub = {"news": "news", "recap": "recap", "audiosum": "summaries"}.get(mode, "")
    d = OUTPUT_DIR / sub if sub else OUTPUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_path(filename: str, mode: str = "news") -> pathlib.Path:
    """Full path for an artifact file, routed to the mode's folder."""
    p = pathlib.Path(filename)
    if p.is_absolute():
        return p
    return output_dir(mode) / filename


def save_news_to_markdown(filename: str, content: str) -> Dict[str, str]:
    """Saves the given content to a Markdown file under OUTPUT_DIR."""
    try:
        if not filename.endswith(".md"):
            filename += ".md"
        file_path = output_path(filename)
        file_path.write_text(content, encoding="utf-8")
        return {"status": "success",
                "message": f"Successfully saved news to {file_path.resolve()}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to save file: {str(e)}"}


def read_transcript_file(filepath: str) -> Dict[str, str]:
    """Reads a meeting transcript file (txt/md/vtt/srt/docx) into text.

    Used by the meeting-recap workflow instead of web_search. Returns a dict
    (not a plain string) so ADK wraps it as structured tool output. Relative
    paths resolve against OUTPUT_DIR first, then TRANSCRIPTS_DIR, then cwd.
    """
    try:
        src = pathlib.Path(filepath)
        if not src.is_absolute():
            for base in (OUTPUT_DIR, TRANSCRIPTS_DIR, pathlib.Path.cwd()):
                cand = base / filepath
                if cand.exists():
                    src = cand
                    break
            else:
                src = pathlib.Path.cwd() / filepath
        if not src.exists():
            return {"status": "error", "message": f"File not found: {filepath}"}
        if src.suffix.lower() == ".docx":
            import zipfile
            with zipfile.ZipFile(src) as z:
                with z.open("word/document.xml") as f:
                    xml = f.read().decode("utf-8", errors="replace")
            import html as _html
            text = _html.unescape(re.sub(r"<[^>]+>", " ", xml))
            text = re.sub(r"[ \t]+", " ", text)
        else:
            text = src.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return {"status": "error", "message": "Transcript file is empty."}
        return {"status": "success", "transcript": text,
                "message": f"Read {len(text)} characters from {src.name}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to read transcript: {str(e)[:200]}"}


# --- local speech-to-text (faster-whisper) + one-shot LLM summary ----------
# Used by the UI's "audio recording" input (Meeting Recap tab). Produces a
# timestamped transcript, then a text-only summary with key highlights.
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "small")

# UI sets AUDIO_BASENAME (filename) and AUDIO_MODE (news/recap) so generated
# podcasts land in the right artifacts folder.
AUDIO_BASENAME = ""
AUDIO_MODE = "news"

# Whisper model cache: the model is loaded ONCE (the UI pre-warms it in a
# background thread at server startup) and reused for every transcription.
# Model loading is the slow part (~40s+ for 'small'); transcribing an
# already-warm model avoids re-running the ctranslate2 init that can
# deadlock inside the uvicorn app process.
_WHISPER_CACHE: Dict[str, Any] = {}
_WHISPER_LOCK = threading.Lock()


def get_whisper_model(model_name: str = None):
    """Load a faster-whisper model once and cache it (thread-safe)."""
    from faster_whisper import WhisperModel
    name = model_name or WHISPER_MODEL_NAME
    with _WHISPER_LOCK:
        model = _WHISPER_CACHE.get(name)
        if model is None:
            model = WhisperModel(name, device="cpu", compute_type="int8")
            _WHISPER_CACHE[name] = model
        return model


def prewarm_whisper(model_name: str = None) -> Dict[str, Any]:
    """Load the whisper model into the cache without transcribing anything.

    Intended to be called from a background thread at server startup so run
    starts reuse the warm model. Never raises; returns {status, message}.
    """
    name = model_name or WHISPER_MODEL_NAME
    try:
        get_whisper_model(name)
        return {"status": "success", "message": f"whisper model '{name}' ready"}
    except Exception as e:
        return {"status": "error", "message": f"whisper prewarm failed: {str(e)[:150]}"}


def whisper_ready(model_name: str = None) -> bool:
    """True if the given whisper model is already loaded in the cache."""
    return (model_name or WHISPER_MODEL_NAME) in _WHISPER_CACHE

_SUMMARY_PROMPT_TEMPLATE = """You are an expert meeting analyst. Below is a timestamped
transcript of an audio recording. Write a concise summary of the recording.

Requirements:
- Write ALL text in {lang_label}.
- Keep timestamps like [mm:ss] or [hh:mm:ss] EXACTLY as they appear in the transcript.
- Do NOT invent content that is not in the transcript.
- Speaker names mentioned in the audio stay in their original form.

Output ONLY markdown with exactly these sections:
# <short title for the recording>
## Overview
<2-4 sentence overall summary>
## Key Highlights
<bullet list of the 5-10 most important moments, each starting with its timestamp>
## Action Items
<markdown table with Task | Owner | Deadline columns, or 'None mentioned'>
## Open Questions
<bullet list of unresolved questions/risks, or 'None mentioned'>

=== TRANSCRIPT START ===
{transcript}
=== TRANSCRIPT END ==="""


def transcribe_audio_file(filepath: str, model_name: str = None,
                          progress_cb=None) -> Dict[str, Any]:
    """Transcribe an audio/video recording locally with faster-whisper.

    Returns a dict with `status`, `transcript` (timestamped plain text),
    `duration_s` and `language`. Blocks until done; call from a worker
    thread. `progress_cb(percent: float, message: str)` is optional.
    """
    try:
        src = pathlib.Path(filepath)
        if not src.is_absolute():
            for base in (RECORDINGS_DIR, pathlib.Path.cwd()):
                cand = base / filepath
                if cand.exists():
                    src = cand
                    break
            else:
                src = pathlib.Path.cwd() / filepath
        if not src.exists():
            return {"status": "error", "message": f"File not found: {filepath}"}

        model_name = model_name or WHISPER_MODEL_NAME
        if progress_cb:
            progress_cb(5.0, f"loading whisper model '{model_name}'")
        # cached: after the startup pre-warm this returns instantly instead
        # of re-initialising ctranslate2 (the historical deadlock point)
        model = get_whisper_model(model_name)

        if progress_cb:
            progress_cb(10.0, f"transcribing {src.name}")
        segments, info = model.transcribe(str(src), vad_filter=True)
        duration = float(info.duration or 0.0)

        lines: List[str] = []
        for seg in segments:
            ts = time.strftime("%H:%M:%S", time.gmtime(seg.start))
            ts = ts[3:] if ts.startswith("00:") else ts  # hh->mm when < 1h
            lines.append(f"[{ts}] {seg.text.strip()}")
            if progress_cb and duration > 0:
                pct = min(95.0, 10.0 + 85.0 * (float(seg.end) / duration))
                progress_cb(pct, f"[{ts}] {seg.text.strip()[:60]}")
        text = "\n".join(lines).strip()
        if not text:
            return {"status": "error", "message": "No speech detected in the audio."}

        return {"status": "success", "transcript": text,
                "duration_s": duration, "language": info.language,
                "message": f"Transcribed {src.name} ({duration:.0f}s, {len(lines)} segments)"}
    except Exception as e:
        return {"status": "error", "message": f"Transcription failed: {str(e)[:200]}"}


def summarize_transcript_text(transcript: str, lang_label: str = "English",
                              model: str = None) -> Dict[str, Any]:
    """One-shot LLM summary of a transcript via the embedded Ollama proxy.

    Returns {status, summary, message}. Uses a single chat completion with
    no tools, so it cannot stall mid-workflow.
    """
    try:
        ensure_proxy_running()
        payload = {
            "model": _strip_model_prefix(model or OLLAMA_MODEL),
            "messages": [
                {"role": "system", "content": "You produce precise, well-structured meeting summaries in markdown."},
                {"role": "user", "content": _SUMMARY_PROMPT_TEMPLATE.format(lang_label=lang_label, transcript=transcript)},
            ],
            "stream": False,
            "temperature": 0.2,
        }
        result = _post_json(f"{OLLAMA_CLOUD_HOST}/api/chat", payload, OLLAMA_CLOUD_API_KEY)
        content = (result.get("message") or {}).get("content", "")
        if not content.strip():
            return {"status": "error", "message": "LLM returned an empty summary."}
        return {"status": "success", "summary": content.strip(),
                "message": f"Summary generated ({len(content)} chars)"}
    except Exception as e:
        return {"status": "error", "message": f"Summarization failed: {str(e)[:200]}"}


# --- edge-tts based podcast audio (replaces Gemini TTS from the lesson) ----
# Hosts are configurable: podcast_ui.py replaces SPEAKERS from config.json
# (1-4 hosts, each {name, voice, persona}). Joe/Jane are the defaults.
DEFAULT_SPEAKERS = [
    {"name": "Joe", "voice": "en-US-GuyNeural",
     "persona": "the enthusiastic host who opens each segment"},
    {"name": "Jane", "voice": "en-US-JennyNeural",
     "persona": "the analytical co-host who adds depth and data"},
]
SPEAKERS: List[Dict[str, str]] = [dict(s) for s in DEFAULT_SPEAKERS]

# Backwards-compatible aliases (podcast_ui.apply_config keeps them in sync)
JOE_VOICE = DEFAULT_SPEAKERS[0]["voice"]
JANE_VOICE = DEFAULT_SPEAKERS[1]["voice"]

# Generic "<Name>: <text>" line matcher. Only configured speaker names are
# accepted, so stray 'URL:'-style text or markdown never becomes a segment.
_SPEAKER_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ .'-]{0,30}?)\s*:\s*(.+?)\s*$",
                              re.IGNORECASE | re.DOTALL)


def _speaker_voice_map() -> Dict[str, str]:
    """Configured speaker name (lowercased) -> edge-tts voice."""
    return {s["name"].strip().lower(): s["voice"] for s in SPEAKERS
            if s.get("name") and s.get("voice")}


def _segments_from_script(script: str) -> List[tuple]:
    """Parse '<Speaker>: ...' lines into (voice, text) segments.

    Speaker names come from the configured SPEAKERS list (Joe/Jane by
    default); lines with any other label are ignored.
    """
    voice_map = _speaker_voice_map()
    segments: List[tuple] = []
    for line in script.splitlines():
        m = _SPEAKER_LINE_RE.match(line)
        if not m:
            continue
        speaker, text = m.group(1).strip(), m.group(2).strip()
        if not text:
            continue
        voice = voice_map.get(speaker.lower())
        if voice:
            segments.append((voice, text))
    return segments


def generate_podcast_audio(podcast_script: str, tool_context: ToolContext,
                           filename: str = "ai_today_podcast") -> Dict[str, Any]:
    """Generates multi-host podcast audio from a script using edge-tts.

    Args:
        podcast_script: Conversational script with '<Speaker>:' lines.
        tool_context: The ADK tool context.
        filename: Base filename (without extension).

    Returns:
        Dict with status and file information.
    """
    try:
        import edge_tts

        # The UI may set AUDIO_BASENAME to route output per mode (news vs
        # recap); honor it when set.
        filename = AUDIO_BASENAME or filename

        segments = _segments_from_script(podcast_script)
        if not segments:
            names = [s.get("name", "Host") for s in SPEAKERS] or ["Joe", "Jane"]
            expected = " or ".join(f"'{n}: <text>'" for n in names)
            return {
                "status": "error",
                "message": (
                    "No speaker lines found in the script. "
                    f"Format each line as {expected} "
                    f"(configured hosts: {', '.join(names)})."
                ),
            }

        async def _synthesize() -> bytes:
            chunks: List[bytes] = []
            for voice, text in segments:
                tts = edge_tts.Communicate(text=text, voice=voice)
                buf = bytearray()
                async for chunk in tts.stream():
                    if chunk["type"] == "audio":
                        buf.extend(chunk["data"])
                chunks.append(bytes(buf))
            return b"".join(chunks)

        # edge-tts is async but ADK tool calls already run inside an event
        # loop, so asyncio.run() here would fail. Run the synthesis in a
        # separate thread with its own event loop instead.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            audio_data = pool.submit(lambda: asyncio.run(_synthesize())).result()
        if not audio_data:
            return {"status": "error", "message": "edge-tts returned no audio data."}

        if not filename.endswith(".mp3"):
            filename += ".mp3"
        file_path = output_path(filename, AUDIO_MODE)
        file_path.write_bytes(audio_data)

        return {
            "status": "success",
            "message": f"Successfully generated and saved podcast audio to {file_path.resolve()}",
            "file_path": str(file_path.resolve()),
            "file_size": len(audio_data),
        }
    except Exception as e:
        return {"status": "error", "message": f"Audio generation failed: {str(e)[:200]}"}


# ===========================================================================
# SECTION 4 - Callbacks (from the lesson; google_search -> web_search)
# ===========================================================================
WHITELIST_DOMAINS = ["techcrunch.com", "venturebeat.com", "theverge.com",
                     "technologyreview.com", "arstechnica.com"]

# Overridable search knobs (podcast_ui.py may set these from config.json)
SEARCH_REGION = "us-en"
SEARCH_TIMELIMIT = "w"
SEARCH_MAX_RESULTS = 8


def filter_news_sources_callback(tool, args, tool_context):
    """Enforce that web_search queries only use whitelisted domains."""
    if tool.name == "web_search":
        original_query = args.get("query", "")
        if any(f"site:{domain}" in original_query.lower() for domain in WHITELIST_DOMAINS):
            return None
        whitelist_query_part = " OR ".join(f"site:{domain}" for domain in WHITELIST_DOMAINS)
        args["query"] = f"{original_query} {whitelist_query_part}"
        print(f"MODIFIED query to enforce whitelist: '{args['query']}'")
    return None


def enforce_data_freshness_callback(tool, args, tool_context):
    """Add a freshness filter (results from the last week) to search queries.

    Replaces the lesson's Gemini-specific 'tbs=qdr:w' with ddgs's
    timelimit='w' parameter.
    """
    if tool.name == "web_search":
        if not args.get("timelimit"):
            args["timelimit"] = SEARCH_TIMELIMIT
            print("MODIFIED query for freshness: timelimit='%s'" % SEARCH_TIMELIMIT)
    return None


def initialize_process_log(tool_context: ToolContext):
    """Ensure the process_log list exists in the state."""
    if "process_log" not in tool_context.state:
        tool_context.state["process_log"] = []


def inject_process_log_after_search(tool, args, tool_context, tool_response):
    """After a search, extract sourced domains and inject the process log."""
    if tool.name == "web_search" and isinstance(tool_response, str):
        urls = re.findall(r"https?://[^\s/]+", tool_response)
        unique_domains = sorted({urlparse(url).netloc for url in urls})

        if unique_domains:
            sourcing_log = (f"Action: Sourced news from the following domains: "
                            f"{', '.join(unique_domains)}.")
            current_log = tool_context.state.get("process_log", [])
            tool_context.state["process_log"] = [sourcing_log] + current_log

        final_log = tool_context.state.get("process_log", [])
        print(f"CALLBACK LOG: Injecting process log into tool response: {final_log}")
        return {"search_results": tool_response, "process_log": final_log}
    return tool_response


# ===========================================================================
# SECTION 5 - Agents
# ===========================================================================
from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from google.adk.models.lite_llm import LiteLlm

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "openai/gpt-oss:120b")

_PODCASTER_INSTRUCTION_BASE = """
    You are an Audio Generation Specialist. Your single task is to take a provided text script
    and convert it into a multi-speaker audio file using the `generate_podcast_audio` tool.

    Workflow:
    1. Receive the text script from the user or another agent.
    2. Immediately call the `generate_podcast_audio` tool with the provided script and the filename of '__AUDIO_BASENAME__'
    3. Report the result of the audio generation back to the user.
"""

# Default instruction (news mode). podcast_ui.build_agents() swaps the
# basename for recap mode via podcaster_instruction().
_PODCASTER_INSTRUCTION = _PODCASTER_INSTRUCTION_BASE.replace("__AUDIO_BASENAME__", "ai_today_podcast")


def podcaster_instruction(audio_basename: str) -> str:
    """Podcaster instruction with a configurable output audio basename."""
    return _PODCASTER_INSTRUCTION_BASE.replace("__AUDIO_BASENAME__", audio_basename)

_ROOT_INSTRUCTION_BASE = """
    **Your Core Identity:**
    You are a Research Podcast Producer. Your job is to orchestrate a complete workflow: __GOAL_LINE__

__SCOPE_DIRECTIVE__
    **Crucial Rules:**
    1.  **Resilience is Key:** If you encounter an error or cannot find specific information for one item (like fetching a stock ticker), you MUST NOT halt the entire process. Use a placeholder value like "Not Available", and continue to the next step. Your primary goal is to deliver the final report and podcast, even if some data points are missing.
    2.  **Scope Limitation:** Your research is strictly limited to US-listed companies on the NASDAQ exchange. All search queries and analysis must adhere to this constraint.
    3.  **User-Facing Communication:** Your interaction has only two user-facing messages: the initial acknowledgment and the final confirmation. All complex work must happen silently in the background between these two messages.

    **Understanding Callback-Modified Tool Outputs:**
    The `web_search` tool is enhanced by callbacks. Its final output is a JSON object with two keys:
    1.  `search_results`: A string containing the actual search results.
    2.  `process_log`: A list of strings describing the filtering actions performed.

    **Required Conversational Workflow:**
    1.  **Acknowledge and Inform:** The VERY FIRST thing you do is respond to the user with: "__ACK_LINE__ I will enrich the findings where possible and compile a report for you. This might take a moment."
    2.  **Search (Background Step):** Immediately after acknowledging, use the `web_search` tool to find relevant news. Your query must be specifically tailored to the research scope defined above.
__FINANCIAL_STEPS__
    5.  **Structure the Report (Internal Step):** Use the `AINewsReport` schema to structure all gathered information. If financial data was not found for a story, you MUST use "Not Available" in the `financial_context` field. You MUST also populate the `process_log` field in the schema with the `process_log` list from the `web_search` tool's output.
    6.  **Format for Markdown (Internal Step):** Convert the structured `AINewsReport` data into a well-formatted Markdown string. This MUST include a section at the end called "## Data Sourcing Notes" where you list the items from the `process_log`.
    7.  **Save the Report (Background Step):** Save the Markdown string using `save_news_to_markdown` with the filename `ai_research_report.md`.
    8.  **Create Podcast Script (Internal Step):** After saving the report, you MUST convert the structured `AINewsReport` data into a natural, conversational podcast script following the SCRIPT FORMAT REQUIREMENTS section at the end of this instruction (host names, personas and the exact speaker-label format are defined there).
    9.  **Generate Audio (Background Step):** Call the `podcaster_agent` tool, passing the complete conversational script you just created to it.
    10. **Final Confirmation:** After the audio is successfully generated, your final response to the user MUST be: "All done. I've compiled the research report, saved it to `ai_research_report.md`, and generated the podcast audio file for you."
"""


def hosts_directive(speakers: Optional[List[Dict[str, str]]] = None) -> str:
    """SCRIPT FORMAT REQUIREMENTS block for the configured hosts (step 8).

    podcast_ui.build_agents() calls this with the user's host config so the
    producer agent writes scripts for exactly the configured host count,
    names and personas.
    """
    sp = speakers if speakers is not None else SPEAKERS
    sp = [s for s in sp if s.get("name")] or [dict(s) for s in DEFAULT_SPEAKERS]
    if len(sp) == 1:
        n = sp[0]["name"]
        persona = sp[0].get("persona") or "a solo news anchor"
        return (
            "\n    **SCRIPT FORMAT REQUIREMENTS (solo format):**\n"
            f"    Write the podcast as a SOLO NEWS ANCHOR segment delivered by one host,\n"
            f"    '{n}' ({persona}).\n"
            f"    Format every line exactly as '{n}: <text>' - one label per line.\n"
            "    No other speaker labels, no stage directions, no markdown inside lines.\n"
            f"    Open with a hook, cover every story in the report in a natural spoken\n"
            f"    style, and close with a sign-off from '{n}'.\n"
        )
    names = [s["name"] for s in sp]
    persona_lines = "\n".join(
        f"        - '{s['name']}': {s.get('persona') or 'co-host'}" for s in sp)
    fmt = " or ".join(f"'{n}: <text>'" for n in names)
    exchange = " -> ".join(names)
    return (
        "\n    **SCRIPT FORMAT REQUIREMENTS:**\n"
        f"    Write a natural, conversational podcast script between {len(sp)} hosts:\n"
        f"{persona_lines}\n"
        f"    Format every line exactly as {fmt}.\n"
        f"    Alternate speakers naturally (e.g. opening pattern {exchange}) and cover\n"
        "    every story in the report. No stage directions, no markdown inside lines.\n"
    )


def _financial_steps_directive(enabled: bool) -> str:
    """Steps 3-4 block for the root workflow: financials or entity analysis."""
    if enabled:
        return (
            "    3.  **Analyze & Extract Tickers (Internal Step):** Process search results to identify company names and their stock tickers. If a ticker cannot be found, use 'N/A'.\n"
            "    4.  **Get Financial Data (Background Step):** Call the `get_financial_context` tool with the extracted tickers. If the tool returns \"Not Available\" for any ticker, you will accept this and proceed. Do not stop or report an error.\n"
        )
    return (
        "    3.  **Analyze & Extract Key Entities (Internal Step):** Process search results to identify the main people, organisations, places and topics of each story. Note any companies mentioned and their tickers when obvious; otherwise use 'N/A'.\n"
        "    4.  **Enrich Context (Background Step):** Do NOT call the `get_financial_context` tool unless the user explicitly asks for stock data. Use the details from the search results as context.\n"
    )


def root_instruction(goal_line: str = None, scope_directive: str = None,
                     ack_line: str = None, financials: bool = True,
                     speakers: Optional[List[Dict[str, str]]] = None) -> str:
    """Build the news-producer instruction for a topic preset.

    goal_line       one-line job description (after 'complete workflow:')
    scope_directive full '**Scope...' block text (may be empty)
    ack_line        first half of the scripted acknowledgment sentence
    financials      whether steps 3-4 direct the agent to fetch stock data
    """
    goal = goal_line or ("find the latest AI news for US-listed companies on the NASDAQ, "
                         "compile a report, write a script, and generate a podcast audio "
                         "file, all while keeping the user informed.")
    scope = scope_directive if scope_directive is not None else (
        "    **Scope Limitation:** Your research is strictly limited to US-listed companies "
        "on the NASDAQ exchange. All search queries and analysis must adhere to this constraint.\n")
    ack = ack_line or ("Okay, I'll start researching the latest AI news for NASDAQ-listed "
                       "US companies.")
    text = (_ROOT_INSTRUCTION_BASE
            .replace("__GOAL_LINE__", goal)
            .replace("__SCOPE_DIRECTIVE__", scope)
            .replace("__ACK_LINE__", ack)
            .replace("__FINANCIAL_STEPS__", _financial_steps_directive(financials)))
    # renumber the workflow list when financial steps are replaced (both
    # variants keep the same count, so the numbering below stays consistent)
    return text + hosts_directive(speakers)


_ROOT_INSTRUCTION = root_instruction()


# -------------------------------------------------------------------------
# Meeting-recap mode (same producer workflow, transcript instead of search)
# -------------------------------------------------------------------------
RECAP_REPORT_FILE = "meeting_recap.md"

_RECAP_INSTRUCTION_TEMPLATE = """
    **Your Core Identity:**
    You are a Meeting Recap Producer. Your job is to turn a raw meeting transcript into a structured recap document and an engaging multi-host recap podcast, while keeping the user informed.

    **Crucial Rules:**
    1.  **Resilience is Key:** If information for a field is missing from the transcript (like a deadline or attendee), use a placeholder such as "Not specified" and continue. Never halt the process.
    2.  **Faithfulness:** Only use what is actually in the transcript. Do not invent decisions or quotes. Attribute statements to speakers when the transcript names them.
    3.  **User-Facing Communication:** Your interaction has only two user-facing messages: the initial acknowledgment and the final confirmation. All complex work must happen silently in the background between these two messages.

    **Required Conversational Workflow:**
    1.  **Acknowledge and Inform:** The VERY FIRST thing you do is respond to the user with: "Okay, I'll read the meeting transcript, extract the key decisions, discussion and action items, and produce a recap document and podcast for you. This might take a moment."
    2.  **Read the Transcript (Background Step):** The full transcript is provided below after the marker '=== TRANSCRIPT START ==='. If a `read_transcript_file` tool result containing a `transcript` field is also present in the conversation, use that content; otherwise use the transcript text below.
    3.  **Extract Key Points (Internal Step):** Identify the meeting date (if any), attendees, the most important decisions, the flow of the discussion, action items with owners and deadlines, and any open questions or risks.
    4.  **Structure the Recap (Internal Step):** Use the `MeetingRecap` schema to structure everything found.
    5.  **Format for Markdown (Internal Step):** Convert the structured recap into a well-formatted Markdown string with these sections: '## Key Decisions', '## Discussion Summary', '## Action Items' (a table with Task / Owner / Deadline columns), '## Open Questions', and a final '## Notes' section listing any caveats (e.g. parts of the transcript that were unclear).
    6.  **Save the Recap (Background Step):** Save the Markdown string using `save_news_to_markdown` with the filename `meeting_recap.md`.
    7.  **Create Podcast Script (Internal Step):** Convert the structured recap into a natural, conversational recap podcast following the SCRIPT FORMAT REQUIREMENTS section at the end of this instruction (host names, personas and the exact speaker-label format are defined there). Cover the decisions first, then the discussion highlights, then the action items.
    8.  **Generate Audio (Background Step):** Call the `podcaster_agent` tool, passing the complete conversational script you just created to it.
    9.  **Final Confirmation:** After the audio is successfully generated, your final response to the user MUST be: "All done. I've compiled the meeting recap, saved it to `meeting_recap.md`, and generated the recap podcast audio for you."
"""


def recap_instruction(speakers: Optional[List[Dict[str, str]]] = None) -> str:
    """Full recap producer instruction: template + host script requirements."""
    return _RECAP_INSTRUCTION_TEMPLATE + hosts_directive(speakers)


RECAP_WORKFLOW_STEPS: List[tuple] = [
    (1, "Acknowledge", "Confirm to user that recap is starting", "root"),
    (2, "Read transcript", "load transcript text / file", "root"),
    (3, "Extract key points", "decisions, discussion, owners", "root"),
    (4, "Structure recap", "fill MeetingRecap schema", "root"),
    (5, "Format markdown", "render recap document", "root"),
    (6, "Save recap", "save_news_to_markdown", "root"),
    (7, "Write script", "host recap script", "root"),
    (8, "Generate audio", "podcaster_agent -> edge-tts mp3", "podcaster"),
    (9, "Confirm done", "final message to user", "root"),
]

podcaster_agent = Agent(
    name="podcaster_agent",
    model=LiteLlm(model=OLLAMA_MODEL),
    instruction=_PODCASTER_INSTRUCTION,
    tools=[generate_podcast_audio],
)

root_agent = Agent(
    name="ai_news_researcher",
    model=LiteLlm(model=OLLAMA_MODEL),
    instruction=_ROOT_INSTRUCTION,
    tools=[
        web_search,
        get_financial_context,
        save_news_to_markdown,
        AgentTool(agent=podcaster_agent),
    ],
    # NOTE: the notebook set output_schema=AINewsReport here. It is dropped
    # because ADK disables tool use when output_schema is set, and the
    # lesson's own 10-step workflow requires tool calls plus a plain-text
    # final confirmation. The schema classes above still guide structure.
    before_tool_callback=[
        filter_news_sources_callback,
        enforce_data_freshness_callback,
    ],
    after_tool_callback=[
        inject_process_log_after_search,
    ],
)

# ===========================================================================
# SECTION 6 - CLI loop (replaces 'adk web' + notebook display cells)
# ===========================================================================
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "lesson6_podcast_agent"
USER_ID = "local_user"
SESSION_ID = "session_001"

REPORT_FILE = "ai_research_report.md"
AUDIO_FILE = "ai_today_podcast.mp3"
AUDIO_BASENAME = "ai_today_podcast"  # overridable by podcast_ui per mode
AUDIO_MODE = "news"  # overridable by podcast_ui per mode (routes to artifacts/<mode>)

# Max auto-continue nudges when the model stalls mid-workflow
MAX_AUTO_CONTINUE = 10


def _banner(mode: str = "news", report_file: str = None, audio_file: str = None) -> None:
    key_ok = "yes" if OLLAMA_CLOUD_API_KEY.strip() else "NO"
    report_file = report_file or (RECAP_REPORT_FILE if mode == "recap" else REPORT_FILE)
    audio_file = audio_file or AUDIO_FILE
    mode_label = "Recap Agent" if mode == "recap" else "Research Agent"
    print("=" * 70)
    print(f"Lesson 6 - {mode_label} (Ollama Cloud)")
    print("=" * 70)
    print(f"  model        : {OLLAMA_MODEL}")
    print(f"  proxy        : http://{PROXY_HOST}:{PROXY_PORT}")
    print(f"  OLLAMA_API_KEY set: {key_ok}")
    if not key_ok.strip():
        print("  !! Fill OLLAMA_API_KEY in .env before expecting real results.")
    print(f"  artifacts    : {report_file} / {audio_file}")
    print("  commands     : exit / quit to leave")
    print("=" * 70)


def _open_in_default_app(path: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - intended Windows behavior
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')  # noqa: S605
        else:
            os.system(f'xdg-open "{path}"')  # noqa: S605
    except Exception as e:
        print(f"(could not open {path}: {e})")


async def _run_agent_turn(runner, session_id: str, text: str) -> str:
    """Run one agent turn to completion and return the final text."""
    content = types.Content(role="user", parts=[types.Part(text=text)])
    final_text = ""
    try:
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session_id, new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = "".join(
                    p.text or "" for p in event.content.parts if p.text
                )
    except KeyboardInterrupt:
        print("\n[interrupted - agent turn aborted]")
        return ""
    except Exception as e:
        print(f"[error from agent turn] {e}")
        return ""
    return final_text


def _build_recap_root() -> Agent:
    """Recap-mode producer agent (transcript input, no web tools)."""
    return Agent(
        name="meeting_recap_producer",
        model=LiteLlm(model=OLLAMA_MODEL),
        instruction=recap_instruction(),
        tools=[
            read_transcript_file,
            save_news_to_markdown,
            AgentTool(agent=podcaster_agent),
        ],
    )


async def main() -> None:
    ensure_proxy_running()

    # CLI mode selection: news (default) | recap [--transcript FILE]
    mode = "news"
    transcript_path = None
    argv = [a for a in sys.argv[1:]]
    if "--transcript" in argv:
        i = argv.index("--transcript")
        if i + 1 < len(argv):
            transcript_path = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if argv and argv[0].lower() in ("news", "recap"):
        mode = argv[0].lower()
        argv = argv[1:]
    if argv:
        print(f"[ignoring unknown args: {' '.join(argv)}]")

    if mode == "recap":
        transcript = ""
        if transcript_path:
            result = read_transcript_file(transcript_path)
            if result.get("status") != "success":
                print(f"[transcript error] {result.get('message')}")
                return
            transcript = result["transcript"]
            print(f"[transcript loaded] {transcript_path} ({len(transcript)} chars)")
        else:
            print("Paste or type the meeting transcript; finish with a line containing only END:")
            lines: List[str] = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "END":
                    break
                lines.append(line)
            transcript = "\n".join(lines).strip()
            if not transcript:
                print("[no transcript provided - bye]")
                return
        user_text = ("Create a meeting recap podcast from the following transcript.\n"
                     "=== TRANSCRIPT START ===\n" + transcript + "\n=== TRANSCRIPT END ===")
        agent = _build_recap_root()
    else:
        user_text = None  # asked interactively in the loop below
        agent = root_agent

    session_service = InMemorySessionService()
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID,
                                         session_id=SESSION_ID)

    runner = Runner(agent=agent, app_name=APP_NAME,
                    session_service=session_service)

    _banner(mode)
    cwd = pathlib.Path.cwd()
    audio_file = AUDIO_FILE

    while True:
        try:
            if user_text is None:
                user_text = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user_text:
            continue
        if user_text.lower() in ("exit", "quit"):
            print("Bye.")
            break

        print("[agent working... this can take a few minutes]")
        final_text = await _run_agent_turn(runner, SESSION_ID, user_text)
        if final_text:
            print("\nAgent> " + final_text)
        else:
            print("\nAgent> (no final response text)")

        # The model may end its turn after the acknowledgment (or any other
        # mid-workflow pause) without tool calls. Keep nudging it to continue
        # the workflow until the audio artifact appears or it stops
        # responding, bounded to avoid an infinite loop.
        audio_path = cwd / audio_file
        nudges = 0
        while nudges < MAX_AUTO_CONTINUE and not audio_path.exists():
            if not final_text:
                break
            nudges += 1
            print(f"\n[auto-continue {nudges}]")
            final_text = await _run_agent_turn(runner, SESSION_ID, "continue")
            if final_text:
                print("\nAgent> " + final_text)
            audio_path = cwd / audio_file

        # Open artifacts if they exist
        report_path = cwd / (RECAP_REPORT_FILE if mode == "recap" else REPORT_FILE)
        if report_path.exists():
            print(f"[report ready] {report_path.resolve()}")
        if audio_path.exists():
            print(f"[audio ready] {audio_path.resolve()} - opening player...")
            _open_in_default_app(str(audio_path))

        # recap mode processes one transcript per invocation
        if mode == "recap":
            print("\nBye.")
            break
        user_text = None  # back to interactive news mode


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye.")