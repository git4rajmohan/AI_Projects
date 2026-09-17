"""
Podcast Agent Web UI
====================

FastAPI app that wraps lesson6_podcast_agent.py (the engine) and shows the
workflow live in the browser:

  grey  = not started | yellow (pulsing) = running | green = done | red = error

Run:
    .venv\\Scripts\\python.exe podcast_ui.py
    # open http://127.0.0.1:8000

Features
--------
- Workflow stepper at the top (10 pills with connector line, live colors)
- Full config panel (model, whitelist domains, search, TTS voices,
  filenames, nudge limit) persisted to config.json
- Voice preview buttons (hear Joe/Jane without a full run)
- Live log console, rendered markdown report, inline audio player
- Per-step elapsed-time badges, run history, stop button
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

import lesson6_podcast_agent as engine

BASE_DIR = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
UI_PORT = int(os.getenv("PODCAST_UI_PORT", "8000"))

# ---------------------------------------------------------------------------
# Workflow steps per mode (news = 10-step lesson flow, recap = 9-step flow)
# agent: which agent owns the step (root = news producer, recap = recap
# producer, podcaster = audio specialist)
# ---------------------------------------------------------------------------
AGENTS = {
    "root": {"name": "Research Agent", "icon": "\U0001F50D", "role": "Producer"},
    "recap": {"name": "Recap Agent", "icon": "\U0001F4CB", "role": "Producer"},
    "podcaster": {"name": "Voice Agent", "icon": "\U0001F3A7", "role": "Audio Specialist"},
    "stt": {"name": "Transcription Engine", "icon": "\U0001F3A4", "role": "Speech-to-Text"},
}


def root_agent_meta(cfg: Dict[str, Any]) -> Dict[str, str]:
    """AGENTS['root'] display info resolved for the active topic preset."""
    p = get_preset(cfg)
    return {"name": p.get("agent_name", "Research Agent"),
            "icon": p.get("icon", "\U0001F50D"), "role": "Producer"}

NEWS_WORKFLOW_STEPS = [
    (1, "Acknowledge", "Confirm to user that research is starting", "root"),
    (2, "Search news", "web_search on whitelisted domains (last week)", "root"),
    (3, "Extract tickers", "identify companies + NASDAQ tickers", "root"),
    (4, "Financial data", "get_financial_context via yfinance", "root"),
    (5, "Structure report", "fill AINewsReport schema", "root"),
    (6, "Format markdown", "render report incl. Data Sourcing Notes", "root"),
    (7, "Save report", "save_news_to_markdown", "root"),
    (8, "Write script", "Joe/Jane conversational script", "root"),
    (9, "Generate audio", "podcaster_agent -> edge-tts mp3", "podcaster"),
    (10, "Confirm done", "final message to user", "root"),
]

RECAP_STEPS_UI = [(n, t, d, ("recap" if a == "root" else a))
                  for n, t, d, a in engine.RECAP_WORKFLOW_STEPS]

# audio-recording path: upload -> transcribe -> summarize -> save (text only)
AUDIOSUM_STEPS_UI = [
    (1, "Receive audio", "upload stored", "recap"),
    (2, "Transcribe audio", "faster-whisper with live progress", "stt"),
    (3, "Summarize", "one LLM pass: overview + highlights", "recap"),
    (4, "Save summary", "write audio_summary.md", "recap"),
]

WORKFLOW_STEPS_BY_MODE = {
    "news": NEWS_WORKFLOW_STEPS,
    "recap": RECAP_STEPS_UI,
    "audiosum": AUDIOSUM_STEPS_UI,
}

# kept for backwards compatibility with anything importing WORKFLOW_STEPS
WORKFLOW_STEPS = NEWS_WORKFLOW_STEPS

# ---------------------------------------------------------------------------
# Topic presets: one dict per research focus. A preset swaps prompt prefill,
# whitelist domains, region/freshness, the producer agent's goal/scope text,
# the agent display name+icon and the stepper labels. "custom" lets the user
# type their own prompt + whitelist. financials=False presets skip the
# yfinance step (its pills are auto-marked done).
# ---------------------------------------------------------------------------
TOPIC_PRESETS: Dict[str, Dict[str, Any]] = {
    "ai_nasdaq": {
        "label": "AI + market news (default)",
        "icon": "\U0001F4F0",
        "prompt": "Research the latest AI news for NASDAQ-listed US companies",
        "whitelist": ["techcrunch.com", "venturebeat.com", "theverge.com",
                      "technologyreview.com", "arstechnica.com"],
        "region": "us-en",
        "goal_line": ("find the latest AI news for US-listed companies on the NASDAQ, "
                      "compile a report, write a script, and generate a podcast audio "
                      "file, all while keeping the user informed."),
        "scope": ("    **Scope Limitation:** Your research is strictly limited to US-listed "
                  "companies on the NASDAQ exchange. All search queries and analysis must "
                  "adhere to this constraint.\n"),
        "ack": "Okay, I'll start researching the latest AI news for NASDAQ-listed US companies.",
        "financials": True,
        "agent_name": "AI & Markets Research Agent",
        "step_labels": None,  # None = use NEWS_WORKFLOW_STEPS unchanged
    },
    "tech": {
        "label": "Tech industry news",
        "icon": "\U0001F4BB",
        "prompt": "Research the latest technology industry news: product launches, "
                  "big-company moves and startup funding",
        "whitelist": ["techcrunch.com", "arstechnica.com", "theverge.com",
                      "engadget.com", "wired.com", "venturebeat.com"],
        "region": "us-en",
        "goal_line": ("find the latest technology industry news, compile a report, "
                      "write a script, and generate a podcast audio file, all while "
                      "keeping the user informed."),
        "scope": ("    **Scope Limitation:** Research is limited to the technology "
                  "industry: product launches, major tech companies, startups and "
                  "funding news. Do not research unrelated topics.\n"),
        "ack": "Okay, I'll start researching the latest technology industry news.",
        "financials": True,
        "agent_name": "Tech Research Agent",
        "step_labels": {3: ("Extract companies", "identify companies + tickers"),
                        4: ("Financial data", "get_financial_context via yfinance")},
    },
    "research": {
        "label": "Research / academic",
        "icon": "\U0001F52C",
        "prompt": "Research the latest notable research papers and scientific "
                  "breakthroughs in AI and summarize the key findings",
        "whitelist": ["arxiv.org", "nature.com", "science.org", "mit.edu",
                      "openreview.net", "technologyreview.com"],
        "region": "us-en",
        "goal_line": ("find the latest notable research and academic findings, "
                      "compile a report, write a script, and generate a podcast audio "
                      "file, all while keeping the user informed."),
        "scope": ("    **Scope Limitation:** Research is limited to scientific/academic "
                  "sources: papers, preprints, university announcements and peer-reviewed "
                  "coverage. No gossip or speculation.\n"),
        "ack": "Okay, I'll start researching the latest notable research findings.",
        "financials": False,
        "agent_name": "Academic Research Agent",
        "step_labels": {3: ("Extract key findings", "papers, authors, results"),
                        4: ("Enrich context", "details from sources (no stock data)")},
    },
    "entertainment_in": {
        "label": "Entertainment news \u2014 India",
        "icon": "\U0001F3AC",
        "prompt": "Find the latest entertainment news in India: Bollywood, OTT "
                  "releases, television and music",
        "whitelist": ["bollywoodhungama.com", "koimoi.com", "indianexpress.com",
                      "hindustantimes.com", "timesofindia.indiatimes.com",
                      "pinkvilla.com"],
        "region": "in-en",
        "goal_line": ("find the latest entertainment news in India, compile a report, "
                      "write a script, and generate a podcast audio file, all while "
                      "keeping the user informed."),
        "scope": ("    **Scope Limitation:** Research is limited to entertainment news "
                  "from India (Bollywood, OTT platforms, television, music). Ignore "
                  "entertainment news from other countries unless it majorly involves "
                  "Indian cinema.\n"),
        "ack": "Okay, I'll start researching the latest entertainment news from India.",
        "financials": False,
        "agent_name": "Entertainment Research Agent",
        "step_labels": {3: ("Extract key entities", "films, stars, studios, platforms"),
                        4: ("Enrich context", "details from sources (no stock data)")},
    },
    "custom": {
        "label": "Custom (my own prompt + whitelist)",
        "icon": "\u270F\uFE0F",
        "prompt": "",
        "whitelist": [],
        "region": "us-en",
        "goal_line": ("research the topic the user asks for in their prompt, compile a "
                      "report, write a script, and generate a podcast audio file, all "
                      "while keeping the user informed."),
        "scope": "",
        "ack": "Okay, I'll research the topic you asked for.",
        "financials": False,
        "agent_name": "Research Agent",
        "step_labels": {3: ("Extract key entities", "people, orgs, topics"),
                        4: ("Enrich context", "details from sources (no stock data)")},
    },
}


def get_preset(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Resolved preset dict for cfg['topic_preset'] (default: ai_nasdaq)."""
    key = cfg.get("topic_preset", "ai_nasdaq")
    return TOPIC_PRESETS.get(key, TOPIC_PRESETS["ai_nasdaq"])


def preset_key(cfg: Dict[str, Any]) -> str:
    key = cfg.get("topic_preset", "ai_nasdaq")
    return key if key in TOPIC_PRESETS else "ai_nasdaq"


def news_steps_for(cfg: Dict[str, Any]) -> List[tuple]:
    """News workflow steps with preset-specific labels."""
    base = [list(s) for s in NEWS_WORKFLOW_STEPS]
    p = get_preset(cfg)
    for i, (n, _t, _d, _a) in enumerate(base):
        if p.get("step_labels") and n in p["step_labels"]:
            t, d = p["step_labels"][n]
            base[i][1], base[i][2] = t, d
    return [tuple(s) for s in base]

# ---------------------------------------------------------------------------
# Languages: report/script language + native edge-tts voices per language.
# All voices below ship with edge-tts (Microsoft neural voices).
# ---------------------------------------------------------------------------
LANGUAGES = {
    "en": {"label": "English", "joe": "en-US-GuyNeural", "jane": "en-US-JennyNeural"},
    "ja": {"label": "日本語 (Japanese)", "joe": "ja-JP-KeitaNeural", "jane": "ja-JP-NanamiNeural"},
    "zh": {"label": "中文 (Chinese)", "joe": "zh-CN-YunjianNeural", "jane": "zh-CN-XiaoxiaoNeural"},
    "ta": {"label": "தமிழ் (Tamil)", "joe": "ta-IN-ValluvarNeural", "jane": "ta-IN-PallaviNeural"},
    "hi": {"label": "हिन्दी (Hindi)", "joe": "hi-IN-MadhurNeural", "jane": "hi-IN-SwaraNeural"},
    "es": {"label": "Español (Spanish)", "joe": "es-ES-AlvaroNeural", "jane": "es-ES-ElviraNeural"},
    "fr": {"label": "Français (French)", "joe": "fr-FR-HenriNeural", "jane": "fr-FR-DeniseNeural"},
    "de": {"label": "Deutsch (German)", "joe": "de-DE-ConradNeural", "jane": "de-DE-KatjaNeural"},
    "ko": {"label": "한국어 (Korean)", "joe": "ko-KR-InJoonNeural", "jane": "ko-KR-SunHiNeural"},
    "pt": {"label": "Português (Portuguese)", "joe": "pt-BR-AntonioNeural", "jane": "pt-BR-FranciscaNeural"},
    "ar": {"label": "العربية (Arabic)", "joe": "ar-SA-HamedNeural", "jane": "ar-SA-ZariyahNeural"},
    "ru": {"label": "Русский (Russian)", "joe": "ru-RU-DmitryNeural", "jane": "ru-RU-SvetlanaNeural"},
}

# ---------------------------------------------------------------------------
# Shared run state (guarded by a lock; read by /api/status)
# ---------------------------------------------------------------------------
STATE_LOCK = threading.Lock()
STATE: Dict[str, Any] = {
    "running": False,
    "run_id": None,
    "mode": "news",
    "prompt": "",
    "steps": {},       # step_no -> {state, started, ended, note, agent}
    "log": [],         # [{ts, text}]
    "agent_text": "",
    "nudges": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "current_agent": None,   # "root" | "recap" | "podcaster" | None
}
WORKER: Dict[str, Any] = {"thread": None, "stop": False}
HISTORY: List[Dict[str, Any]] = []


def _reset_steps(mode: str = "news") -> None:
    cfg = load_config()
    if mode == "news":
        steps_for_mode = news_steps_for(cfg)
    else:
        steps_for_mode = WORKFLOW_STEPS_BY_MODE.get(mode, NEWS_WORKFLOW_STEPS)
    STATE["steps"] = {n: {"state": "idle", "started": None, "ended": None, "note": "",
                          "agent": agent}
                      for n, _t, _d, agent in steps_for_mode}
    # non-financial presets never call get_financial_context: auto-mark the
    # affected pills done so they don't sit idle forever
    if mode == "news" and not get_preset(cfg).get("financials", True):
        for n in (3, 4):
            if n in STATE["steps"]:
                STATE["steps"][n].update(state="done", ended=time.time(),
                                         note="skipped for this preset")
    STATE["current_agent"] = None


def set_current_agent(agent_key: Optional[str]) -> None:
    with STATE_LOCK:
        STATE["current_agent"] = agent_key
        cfg = load_config()
        meta = AGENTS.get(agent_key, {})
        if agent_key == "root" and STATE.get("mode", "news") == "news":
            meta = root_agent_meta(cfg)
    if agent_key:
        log_line(f"[{meta.get('icon', '')} {meta.get('name', agent_key)}] working")


def step_state(step: int) -> Dict[str, Any]:
    with STATE_LOCK:
        return dict(STATE["steps"].get(step, {"state": "idle"}))


def step_start(step: int, note: str = "") -> None:
    mode_steps = WORKFLOW_STEPS_BY_MODE.get(STATE.get("mode", "news"), NEWS_WORKFLOW_STEPS)
    agent = next((a for n, _t, _d, a in mode_steps if n == step), "root")
    with STATE_LOCK:
        s = STATE["steps"].get(step)
        if s and s["state"] in ("idle", "error"):
            s["state"] = "running"
            s["started"] = time.time()
            s["agent"] = agent
            if note:
                s["note"] = note
        STATE["current_agent"] = agent


def step_done(step: int, note: str = "") -> None:
    with STATE_LOCK:
        s = STATE["steps"].get(step)
        if s:
            if s["state"] != "done":
                s["state"] = "done"
                s["ended"] = time.time()
            if note:
                s["note"] = note


def step_error(step: int, note: str = "") -> None:
    with STATE_LOCK:
        s = STATE["steps"].get(step)
        if s:
            s["state"] = "error"
            s["ended"] = time.time()
            if note:
                s["note"] = note


def log_line(text: str) -> None:
    with STATE_LOCK:
        STATE["log"].append({"ts": time.strftime("%H:%M:%S"), "text": text})
        STATE["log"] = STATE["log"][-500:]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "model": os.getenv("OLLAMA_MODEL", "openai/gpt-oss:120b"),
    "whitelist_domains": list(engine.WHITELIST_DOMAINS),
    "search_max_results": 8,
    "search_region": "us-en",
    "search_timelimit": "w",
    "joe_voice": engine.JOE_VOICE,
    "jane_voice": engine.JANE_VOICE,
    "report_file": "ai_research_report.md",
    "audio_file": "ai_today_podcast.mp3",
    "max_auto_continue": 10,
    "language": "en",
    "hosts": [dict(s) for s in engine.DEFAULT_SPEAKERS],
    "recap_report_file": engine.RECAP_REPORT_FILE,
    "recap_audio_file": "meeting_recap.mp3",
    "audio_summary_file": "audio_summary.md",
    "whisper_model": engine.WHISPER_MODEL_NAME,
    "topic_preset": "ai_nasdaq",
    "custom_topic": "",
}


def load_config() -> Dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy (hosts is nested)
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
        except Exception as e:
            log_line(f"[config] failed to read {CONFIG_PATH.name}: {e}")
    return _normalize_hosts(cfg)


def _normalize_hosts(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize cfg['hosts']: 1-4 hosts, str fields, non-empty names/voices.

    Also keeps the legacy joe_voice/jane_voice fields in sync with hosts[0]
    and hosts[1] so old config files and previews keep working.
    """
    hosts = cfg.get("hosts")
    clean: List[Dict[str, str]] = []
    if isinstance(hosts, list):
        for h in hosts[:4]:
            if not isinstance(h, dict):
                continue
            name = str(h.get("name", "")).strip()
            voice = str(h.get("voice", "")).strip()
            persona = str(h.get("persona", "")).strip()
            if name and voice:
                clean.append({"name": name, "voice": voice, "persona": persona})
    if not clean:
        clean = [dict(s) for s in engine.DEFAULT_SPEAKERS]
    cfg["hosts"] = clean
    if len(clean) > 0:
        cfg["joe_voice"] = clean[0]["voice"]
        engine.JOE_VOICE = clean[0]["voice"]
    if len(clean) > 1:
        cfg["jane_voice"] = clean[1]["voice"]
        engine.JANE_VOICE = clean[1]["voice"]
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def apply_config(cfg: Dict[str, Any]) -> None:
    """Push config values into the engine globals the agents/tools read."""
    engine.SPEAKERS = [dict(h) for h in (cfg.get("hosts") or engine.DEFAULT_SPEAKERS)]
    engine.JOE_VOICE = engine.SPEAKERS[0]["voice"]
    engine.JANE_VOICE = (engine.SPEAKERS[1]["voice"] if len(engine.SPEAKERS) > 1
                         else engine.SPEAKERS[0]["voice"])
    engine.WHITELIST_DOMAINS = list(cfg["whitelist_domains"])
    engine.SEARCH_REGION = cfg["search_region"]
    engine.SEARCH_TIMELIMIT = cfg["search_timelimit"]
    engine.SEARCH_MAX_RESULTS = int(cfg["search_max_results"])
    engine.REPORT_FILE = cfg["report_file"]
    engine.AUDIO_FILE = cfg["audio_file"]
    engine.MAX_AUTO_CONTINUE = int(cfg["max_auto_continue"])


def mode_artifacts(cfg: Dict[str, Any], mode: str) -> tuple:
    """(report_filename, audio_filename) for the given mode."""
    if mode == "recap":
        return (cfg.get("recap_report_file", engine.RECAP_REPORT_FILE),
                cfg.get("recap_audio_file", "meeting_recap.mp3"))
    if mode == "audiosum":
        # no audio artifact in this mode; second tuple entry unused
        return (cfg.get("audio_summary_file", "audio_summary.md"),
                cfg.get("recap_audio_file", "meeting_recap.mp3"))
    return cfg["report_file"], cfg["audio_file"]


def build_agents(cfg: Dict[str, Any], mode: str = "news"):
    """Build fresh agents from the engine with current config applied.

    news  -> ai_news_researcher (web_search/financials/save + podcaster)
    recap -> meeting_recap_producer (read_transcript_file/save + podcaster)
    The news producer's goal/scope/acknowledgment come from the active topic
    preset (cfg['topic_preset']); custom presets get a prompt-driven scope.
    """
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.agents import Agent

    apply_config(cfg)
    preset = get_preset(cfg)
    pkey = preset_key(cfg)
    # preset whitelist/region win on save-time; the run overrides use whatever
    # is in config (saved by the UI when the user picks a preset or edits chips)
    if not engine.WHITELIST_DOMAINS and pkey != "custom":
        engine.WHITELIST_DOMAINS = list(preset["whitelist"])
    lang = LANGUAGES.get(cfg.get("language", "en"), LANGUAGES["en"])
    lang_label = lang["label"]
    hosts = cfg["hosts"]

    speaker_names = [h["name"] for h in hosts]
    speaker_list = ", ".join(f"'{n}:'" for n in speaker_names)
    if mode == "recap":
        scope_line = ("    the recap document (title, decisions, summaries, action items),\n"
                      "    and the podcast script. Person and company names stay in their\n"
                      "    original form.\n")
    else:
        scope_line = ("    the research report (title, summaries, every field), the 'Data Sourcing Notes' section,\n"
                      "    and the podcast script. Company names and stock tickers stay in their original form.\n")
    language_directive = (
        "\n    **LANGUAGE REQUIREMENT (MANDATORY):**\n"
        f"    Write ALL user-visible content in {lang_label}. This includes the acknowledgment,\n"
        + scope_line +
        f"    The script speaker labels stay exactly {speaker_list} (Latin letters) so the\n"
        "    text-to-speech engine can assign the correct voices; the spoken text after each\n"
        f"    label must be in {lang_label}.\n"
    )

    model = LiteLlm(model=cfg["model"])

    # per-mode audio basename so recap runs don't overwrite the news mp3
    _report_file, audio_file = mode_artifacts(cfg, mode)
    audio_basename = audio_file[:-4] if audio_file.lower().endswith(".mp3") else audio_file
    engine.AUDIO_BASENAME = audio_basename
    engine.AUDIO_MODE = mode

    podcaster = Agent(
        name="podcaster_agent",
        model=model,
        instruction=engine.podcaster_instruction(audio_basename),
        tools=[engine.generate_podcast_audio],
    )
    if mode == "recap":
        root = Agent(
            name="meeting_recap_producer",
            model=model,
            instruction=(engine.recap_instruction(hosts)
                         + f"\n    **RECAP FILE (MANDATORY):** When saving the recap document, use the filename '{cfg['recap_report_file']}'.\n"
                         + language_directive),
            tools=[
                engine.read_transcript_file,
                engine.save_news_to_markdown,
                engine.AgentTool(agent=podcaster),
            ],
            before_tool_callback=[ui_step_tracker_before],
            after_tool_callback=[ui_step_tracker_after],
        )
    else:
        # topic preset drives the producer's identity, scope and whether the
        # financial (yfinance) step is part of the workflow
        custom_topic = str(cfg.get("custom_topic", "") or "").strip()
        if pkey == "custom" and custom_topic:
            goal_line = (f"research '{custom_topic}' as the user asked, compile a report, "
                         "write a script, and generate a podcast audio file, all while "
                         "keeping the user informed.")
            scope_directive = (f"    **Scope Limitation:** Research is limited to the user's "
                               f"stated topic: {custom_topic}. Ignore unrelated subjects.\n")
            ack_line = f"Okay, I'll start researching {custom_topic}."
        else:
            goal_line = preset["goal_line"]
            scope_directive = preset["scope"]
            ack_line = preset["ack"]
        instruction = engine.root_instruction(
            goal_line=goal_line,
            scope_directive=scope_directive,
            ack_line=ack_line,
            financials=bool(preset.get("financials", True)),
            speakers=hosts,
        )
        root = Agent(
            name="ai_news_researcher",
            model=model,
            instruction=(instruction
                         + language_directive),
            tools=[
                engine.web_search,
                engine.get_financial_context,
                engine.save_news_to_markdown,
                engine.AgentTool(agent=podcaster),
            ],
            before_tool_callback=[ui_step_tracker_before,
                                  engine.filter_news_sources_callback,
                                  engine.enforce_data_freshness_callback],
            after_tool_callback=[ui_step_tracker_after,
                                 engine.inject_process_log_after_search],
        )
    return root


# ---------------------------------------------------------------------------
# UI step-tracking callbacks (map tool calls to workflow steps)
# ---------------------------------------------------------------------------
def ui_step_tracker_before(tool, args, tool_context):
    name = tool.name
    recap = STATE.get("mode") == "recap"
    if name == "web_search":
        set_current_agent("root")
        step_start(2, f"query: {args.get('query', '')[:80]}")
    elif name == "read_transcript_file":
        set_current_agent("recap")
        step_start(2, str(args.get("filepath", ""))[:80])
    elif name == "get_financial_context":
        set_current_agent("root")
        # reaching this tool implies step 3 (ticker extraction) completed
        step_done(3, "tickers: " + ", ".join(args.get("tickers", [])[:6]))
        step_start(4, "tickers: " + ", ".join(args.get("tickers", [])[:6]))
    elif name == "save_news_to_markdown":
        if recap:
            # recap: LLM had to extract (3) + structure (4) + format (5) first
            set_current_agent("recap")
            step_done(3)
            step_done(4)
            step_done(5)
            step_start(6, str(args.get("filename", "")))
        else:
            set_current_agent("root")
            # LLM had to structure (5) + format (6) before saving (7)
            step_done(5)
            step_done(6)
            step_start(7, str(args.get("filename", "")))
    elif name == "podcaster_agent":
        set_current_agent("podcaster")
        if recap:
            step_done(7)
            step_start(8, "edge-tts synthesis")
        else:
            step_done(8)
            step_start(9, "edge-tts synthesis")


def ui_step_tracker_after(tool, args, tool_context, tool_response):
    name = tool.name
    recap = STATE.get("mode") == "recap"
    cfg = load_config()
    report_file, audio_file = mode_artifacts(cfg, STATE.get("mode", "news"))
    if name == "web_search":
        n_results = str(tool_response).count(" | ")
        step_done(2, f"{n_results} result lines")
    elif name == "read_transcript_file":
        resp = tool_response if isinstance(tool_response, dict) else {}
        if resp.get("status") == "success":
            step_done(2, f"{len(resp.get('transcript', ''))} chars")
        else:
            step_error(2, resp.get("message", "read failed"))
    elif name == "get_financial_context":
        step_done(4)
    elif name == "save_news_to_markdown":
        resp = tool_response if isinstance(tool_response, dict) else {}
        if resp.get("status") == "success":
            step_done(6 if recap else 7, resp.get("message", ""))
        else:
            step_error(6 if recap else 7, resp.get("message", "save failed"))
    elif name == "podcaster_agent":
        # The AgentTool result may be a dict or string; look for success/error
        text = json.dumps(tool_response, default=str) if not isinstance(tool_response, str) else tool_response
        audio = engine.output_path(audio_file, "audiosum" if recap else "news")
        if not audio.exists():
            audio = BASE_DIR / audio_file  # legacy location
        if audio.exists():
            step_done(8 if recap else 9, f"{audio.stat().st_size} bytes")
        else:
            step_error(8 if recap else 9, text[:120] if text else "no audio produced")


# ---------------------------------------------------------------------------
# Runner worker thread
# ---------------------------------------------------------------------------
def run_workflow(prompt: str, mode: str = "news") -> None:
    cfg = load_config()
    apply_config(cfg)

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    app_name = "podcast_ui"
    user_id = "ui_user"
    session_id = f"run_{uuid.uuid4().hex[:8]}"

    root_agent = build_agents(cfg, mode)
    report_file, audio_file = mode_artifacts(cfg, mode)

    async def _run() -> str:
        session_service = InMemorySessionService()
        await session_service.create_session(app_name=app_name, user_id=user_id,
                                             session_id=session_id)
        runner = engine.Runner(agent=root_agent, app_name=app_name,
                               session_service=session_service)
        # artifacts live under artifacts/<mode>/ (legacy root copies checked too)
        mode_dir = engine.output_dir("audiosum" if mode == "audiosum" else mode)
        audio_path = mode_dir / audio_file
        if not audio_path.exists():
            audio_path = BASE_DIR / audio_file
        report_path = mode_dir / report_file
        if not report_path.exists():
            report_path = BASE_DIR / report_file

        async def turn(text: str) -> str:
            content = types.Content(role="user", parts=[types.Part(text=text)])
            final = ""
            async for event in runner.run_async(user_id=user_id, session_id=session_id,
                                                new_message=content):
                if event.is_final_response() and event.content and event.content.parts:
                    final = "".join(p.text or "" for p in event.content.parts if p.text)
            return final

        # Step 1 (acknowledge) - first turn
        step_start(1)
        first = await turn(prompt)
        with STATE_LOCK:
            STATE["agent_text"] = first or ""
        if first:
            step_done(1, first[:60])
            log_line(f"Agent> {first[:120]}")

        # Auto-continue loop (same pattern as the CLI)
        nudges = 0
        max_nudges = int(cfg["max_auto_continue"])
        while nudges < max_nudges and not audio_path.exists():
            if WORKER["stop"]:
                log_line("[stopped by user]")
                return
            nudges += 1
            with STATE_LOCK:
                STATE["nudges"] = nudges
            log_line(f"[auto-continue {nudges}/{max_nudges}]")
            nxt = await turn("continue")
            if nxt:
                log_line(f"Agent> {nxt[:120]}")
                with STATE_LOCK:
                    STATE["agent_text"] = nxt

        # Final confirmation (last step of the mode's workflow)
        mode_steps = WORKFLOW_STEPS_BY_MODE.get(mode, NEWS_WORKFLOW_STEPS)
        last_step = max(n for n, _t, _d, _a in mode_steps)
        if audio_path.exists() and report_path.exists():
            step_done(last_step, "artifacts ready")
            log_line("[done] " + ("recap" if mode == "recap" else "report") + " + audio generated")
        else:
            missing = []
            if not report_path.exists():
                missing.append("recap doc" if mode == "recap" else "report")
            if not audio_path.exists():
                missing.append("audio")
            step_error(last_step, "missing: " + ", ".join(missing))
            log_line(f"[incomplete] missing: {', '.join(missing)}")

    try:
        asyncio.run(_run())
    except Exception as e:
        log_line(f"[worker error] {e}")
        with STATE_LOCK:
            STATE["error"] = str(e)


# ---------------------------------------------------------------------------
# Audio-summary worker (no ADK loop: transcribe -> single LLM call -> save)
# ---------------------------------------------------------------------------
TRANSCRIBE_SUBPROCESS_TIMEOUT_S = 900  # hard cap for the transcription subprocess


def _transcribe_in_subprocess(audio_path: pathlib.Path, whisper_model: str,
                              progress) -> Optional[Dict[str, Any]]:
    """Run _transcribe_sub.py in a short-lived subprocess (fallback path).

    Streams its JSON progress lines into the UI log. Returns the final
    result dict, or None if the user pressed Stop. A hard timeout kills a
    hung subprocess instead of freezing the run forever.
    """
    import sys as _sys
    import subprocess as _sp
    proc = _sp.Popen(
        [_sys.executable, "-X", "utf8", str(BASE_DIR / "_transcribe_sub.py"),
         str(audio_path), whisper_model],
        cwd=str(BASE_DIR), stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    result: Optional[Dict[str, Any]] = None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log_line(f"[stt] {line[:100]}")
                continue
            if msg.get("final"):
                result = msg["result"]
            else:
                progress(msg["p"], msg["m"])
                if WORKER["stop"]:
                    proc.kill()
                    return None
        proc.wait(timeout=60)
    except _sp.TimeoutExpired:
        proc.kill()
        log_line("[stt error] transcription subprocess timed out")
        return {"status": "error",
                "message": f"transcription timed out after {TRANSCRIBE_SUBPROCESS_TIMEOUT_S}s"}
    if result is None:
        result = {"status": "error",
                  "message": f"transcription process failed (rc={proc.returncode})"}
    return result


def run_audio_summary(audio_path: pathlib.Path, cfg: Dict[str, Any]) -> None:
    import sys as _sys  # used by the transcription subprocess fallback below
    lang = LANGUAGES.get(cfg.get("language", "en"), LANGUAGES["en"])
    summary_file = cfg.get("audio_summary_file", "audio_summary.md")
    whisper_model = cfg.get("whisper_model", "small")

    # archive previous summary so panels show only the current run
    summ_dir = engine.output_dir("audiosum")
    p = summ_dir / summary_file
    if p.exists():
        stamp = time.strftime("%Y%m%d_%H%M%S")
        p.rename(summ_dir / f"{p.stem}_old_{stamp}{p.suffix}")

    try:
        def _progress(pct: float, msg: str) -> None:
            with STATE_LOCK:
                s = STATE["steps"].get(2)
                if s:
                    s["note"] = f"{pct:.0f}% {msg}"
            log_line(f"[whisper {pct:.0f}%] {msg[:80]}")

        step_done(1, f"{audio_path.stat().st_size} bytes")
        set_current_agent("stt")
        step_start(2, "loading whisper model")
        log_line(f"[stt] transcribing {audio_path.name} "
                 f"(model={whisper_model})")

        # Transcription runs in a clean SUBPROCESS (_transcribe_sub.py) with
        # a hard timeout: faster-whisper (ctranslate2) proved unreliable
        # inside the uvicorn app process, while the subprocess path is
        # verified working with live progress. The startup pre-warm keeps
        # the OS file cache warm so the subprocess model load is faster.
        if WORKER["stop"]:
            log_line("[stopped by user]")
            return
        result = _transcribe_in_subprocess(audio_path, whisper_model,
                                           _progress)
        if WORKER["stop"] and result is None:
            log_line("[stopped by user]")
            return
        if not isinstance(result, dict):
            result = {"status": "error", "message": "transcription returned no result"}
        if result.get("status") != "success":
            step_error(2, result.get("message", "transcription failed"))
            log_line(f"[stt error] {result.get('message')}")
            return
        step_done(2, f"{result['duration_s']:.0f}s audio, {result['language']}")
        log_line(f"[stt] done: {result['message']}")

        # keep the timestamped raw transcript next to the summary
        tf = engine.TRANSCRIPTS_DIR / f"transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        tf.parent.mkdir(parents=True, exist_ok=True)
        tf.write_text(result["transcript"], encoding="utf-8")
        log_line(f"[stt] raw transcript saved: {tf.name}")

        if WORKER["stop"]:
            log_line("[stopped by user]")
            return

        set_current_agent("recap")
        step_start(3, f"language={lang['label']}")
        log_line("[llm] generating summary + key highlights")
        summ = engine.summarize_transcript_text(result["transcript"],
                                                lang_label=lang["label"])
        if summ.get("status") != "success":
            step_error(3, summ.get("message", "summary failed"))
            log_line(f"[llm error] {summ.get('message')}")
            return
        step_done(3, summ.get("message", ""))
        log_line(f"[llm] {summ.get('message')}")

        step_start(4, summary_file)
        out_md = engine.output_path(summary_file, "audiosum")
        out_md.write_text(summ["summary"], encoding="utf-8")
        step_done(4, f"{len(summ['summary'])} chars")
        log_line(f"[done] summary saved to {out_md.name} (artifacts/summaries)")
    except Exception as e:
        log_line(f"[worker error] {e}")
        with STATE_LOCK:
            STATE["error"] = str(e)


def start_run(prompt: str, overrides: Optional[Dict[str, Any]] = None,
              mode: str = "news", transcript: str = "",
              audio_file: str = "") -> bool:
    # merge any unsaved panel settings (language, voices, preset, ...) into
    # config.json so the run uses exactly what the UI shows
    if overrides:
        cfg = load_config()
        for k in DEFAULT_CONFIG:
            if k in overrides:
                cfg[k] = overrides[k]
        # only a non-empty custom topic overrides the stored one
        if overrides.get("topic_preset") == "custom":
            ct = overrides.get("custom_topic")
            if ct is not None:
                cfg["custom_topic"] = str(ct).strip()
        save_config(cfg)

    # audiosum mode: validate the uploaded audio BEFORE touching run state.
    # Returning False after the STATE["running"]=True update below used to
    # leave a zombie run (running=True, no worker thread) that 409'd every
    # later POST until a server restart.
    audio_abs = None
    if mode == "audiosum":
        if not audio_file:
            log_line("[run] rejected: audiosum run without audio_file")
            return False
        audio_abs = engine.output_path(audio_file, "audiosum")
        if not audio_abs.exists():
            audio_abs = BASE_DIR / audio_file  # legacy location
        if not audio_abs.exists():
            log_line(f"[run] rejected: audio file not found: {audio_file}")
            return False

    with STATE_LOCK:
        if STATE["running"]:
            thr = WORKER.get("thread")
            if thr is not None and thr.is_alive():
                return False
            # self-heal: running=True but the worker thread is gone
            log_line("[run] clearing stale run state (worker thread dead)")
            STATE["running"] = False
        # remember the mode BEFORE resetting steps (trackers read it)
        STATE["mode"] = mode if mode in WORKFLOW_STEPS_BY_MODE else "news"
        run_mode = STATE["mode"]

    # archive the previous run's artifacts so the report/audio panels only
    # ever display output from the current run (avoids stale-language files)
    cfg = load_config()
    report_file, audio_file = mode_artifacts(cfg, run_mode)
    mode_dir = engine.output_dir("audiosum" if run_mode == "audiosum" else run_mode)
    for fname in {report_file, audio_file}:
        for cand in (mode_dir / fname, BASE_DIR / fname):
            if cand.exists():
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cand.rename(cand.with_name(f"{cand.stem}_old_{stamp}{cand.suffix}"))
                break

    # recap mode: persist a pasted transcript to the transcripts folder so
    # the agent can load it via read_transcript_file (single ingestion path)
    transcript_file = None
    if run_mode == "recap" and transcript.strip():
        tf = engine.TRANSCRIPTS_DIR / f"transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        tf.parent.mkdir(parents=True, exist_ok=True)
        tf.write_text(transcript, encoding="utf-8")
        transcript_file = tf.name

    with STATE_LOCK:
        STATE.update({
            "running": True, "run_id": uuid.uuid4().hex[:8],
            "prompt": prompt,
            "agent_text": "", "nudges": 0, "started_at": time.time(),
            "finished_at": None, "error": None,
        })
        _reset_steps(run_mode)
        STATE["log"] = []
    WORKER["stop"] = False

    # For recap runs with a pasted transcript, point the agent at the file
    # (audio_abs for audiosum was already validated above)
    run_prompt = prompt
    if run_mode == "recap" and transcript.strip():
        run_prompt = (prompt + "\nUse the read_transcript_file tool on the file '"
                      + transcript_file + "' to load the full transcript.")

    # audiosum mode: the uploaded audio path drives the whole worker
    def _target():
        try:
            if run_mode == "audiosum":
                run_audio_summary(audio_abs, load_config())
            else:
                run_workflow(run_prompt, run_mode)
        finally:
            with STATE_LOCK:
                STATE["running"] = False
                STATE["finished_at"] = time.time()
            r_file, a_file = mode_artifacts(load_config(), run_mode)
    report_file, audio_file = mode_artifacts(cfg, run_mode)
    mode_dir = engine.output_dir("audiosum" if run_mode == "audiosum" else run_mode)
    HISTORY.append({
        "ts": time.strftime("%H:%M:%S"),
        "mode": run_mode,
        "prompt": prompt[:80],
        "report": (mode_dir / r_file).exists() or (BASE_DIR / r_file).exists(),
        "audio": ((mode_dir / a_file).exists() or (BASE_DIR / a_file).exists())
                 if run_mode != "audiosum" else False,
    })

    t = threading.Thread(target=_target, daemon=True)
    WORKER["thread"] = t
    t.start()
    return True


# ---------------------------------------------------------------------------
# Voice preview (no full run needed)
# ---------------------------------------------------------------------------
VOICE_CACHE: Dict[str, bytes] = {}


def synthesize_preview(voice: str, text: str) -> bytes:
    import edge_tts

    async def _synth() -> bytes:
        tts = edge_tts.Communicate(text=text, voice=voice)
        buf = bytearray()
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    key = f"{voice}|{text}"
    if key not in VOICE_CACHE:
        VOICE_CACHE[key] = asyncio.run(_synthesize_preview(voice, text))
    return VOICE_CACHE[key]


async def _synthesize_preview(voice: str, text: str) -> bytes:
    import edge_tts
    tts = edge_tts.Communicate(text=text, voice=voice)
    buf = bytearray()
    async for chunk in tts.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def preview_voice(voice: str, text: str) -> bytes:
    key = f"{voice}|{text}"
    if key not in VOICE_CACHE:
        VOICE_CACHE[key] = asyncio.run(_synthesize_preview(voice, text))
    return VOICE_CACHE[key]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Podcast Agent UI")


@app.on_event("startup")
def _startup() -> None:
    engine.ensure_proxy_running()
    # Pre-warm whisper in a background thread so the first transcribe run
    # uses the warm, cached model instead of stalling on model init.
    STATE["whisper_prewarm"] = {"running": True, "status": "pending",
                                "model": None, "message": "queued"}
    threading.Thread(target=_prewarm_whisper, name="whisper-prewarm",
                     daemon=True).start()


def _prewarm_whisper() -> None:
    """Background startup thread: load the faster-whisper model once.

    The isolated repro proved the model loads fine inside the uvicorn app
    when nothing else touches ctranslate2 (~35s); the cached model is then
    reused by every run, so a run start no longer stalls on model init.
    """
    model_name = load_config().get("whisper_model", "small")
    with STATE_LOCK:
        STATE["whisper_prewarm"] = {"running": True, "model": model_name,
                                    "status": "loading", "message": "loading"}
    result = engine.prewarm_whisper(model_name)
    with STATE_LOCK:
        STATE["whisper_prewarm"] = {"running": False, "model": model_name,
                                    **result}
    log_line(f"[prewarm] {result['message']}")


@app.get("/", response_class=HTMLResponse)
def index():
    return _page()


@app.get("/api/config")
def get_config():
    return load_config()


@app.post("/api/config")
async def post_config(request: Request):
    body = await request.json()
    cfg = load_config()
    for k in DEFAULT_CONFIG:
        if k in body:
            cfg[k] = body[k]
    save_config(cfg)
    return cfg


@app.post("/api/upload")
async def api_upload(request: Request):
    """Accept a raw audio recording upload; return the stored filename."""
    data = await request.body()
    if not data:
        raise HTTPException(400, "empty upload")
    fname = request.query_params.get("filename", "")
    safe = re.sub(r"[^A-Za-z0-9_. -]", "_", pathlib.PurePosixPath(fname).name) or "recording"
    ext = pathlib.Path(safe).suffix.lower()
    if ext not in (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".aac"):
        raise HTTPException(400, f"unsupported audio extension '{ext}'")
    stem = pathlib.Path(safe).stem
    dest = engine.RECORDINGS_DIR / f"recording_{time.strftime('%Y%m%d_%H%M%S')}_{stem[:40]}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    log_line(f"[upload] {dest.name} ({len(data)} bytes)")
    return {"file": dest.name, "size": len(data)}


@app.post("/api/run")
async def api_run(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    mode = body.get("mode") if body.get("mode") in WORKFLOW_STEPS_BY_MODE else "news"
    audio_file = ""
    if mode == "audiosum":
        transcript = ""
        audio_file = str(body.get("audio_file") or "")
        audio_path = BASE_DIR / audio_file if audio_file else None
        if not audio_file or "/" in audio_file or ".." in audio_file \
                or not audio_path or not audio_path.exists():
            raise HTTPException(400, "audio_file missing or not uploaded; POST /api/upload?filename=... first")
        prompt = (body.get("prompt") or "").strip() or \
            "Summarize the uploaded audio recording with key highlights."
    elif mode == "recap":
        transcript = str(body.get("transcript") or "")
        prompt = (body.get("prompt") or "").strip() or \
            "Create a meeting recap podcast from the meeting transcript."
    else:
        transcript = ""
        prompt = (body.get("prompt") or "").strip() or "Research the latest AI news for NASDAQ-listed US companies"
    # panel settings the user may not have saved - pass them through
    overrides = {k: body[k] for k in DEFAULT_CONFIG if k in body and body[k] not in (None, "")}
    ok = start_run(prompt, overrides, mode=mode, transcript=transcript,
                   audio_file=audio_file)
    if not ok:
        raise HTTPException(status_code=409, detail="A run is already in progress")
    return {"started": True, "run_id": STATE["run_id"], "mode": mode}


@app.post("/api/stop")
def api_stop():
    WORKER["stop"] = True
    return {"stopping": True}


@app.get("/api/status")
def api_status():
    cfg = load_config()
    with STATE_LOCK:
        steps = {str(k): v for k, v in STATE["steps"].items()}
        mode = STATE.get("mode", "news")
        payload = {
            "running": STATE["running"],
            "run_id": STATE["run_id"],
            "mode": mode,
            "nudges": STATE["nudges"],
            "log": STATE["log"][-200:],
            "agent_text": STATE["agent_text"],
            "steps": steps,
            "started_at": STATE["started_at"],
            "finished_at": STATE["finished_at"],
            "error": STATE["error"],
            "current_agent": STATE.get("current_agent"),
            "whisper_ready": engine.whisper_ready(cfg.get("whisper_model", "small")),
        }
    report_file, audio_file = mode_artifacts(cfg, mode)
    mode_dir = engine.output_dir("audiosum" if mode == "audiosum" else mode)
    payload["artifacts"] = {
        "report": (mode_dir / report_file).exists() or (BASE_DIR / report_file).exists(),
        "audio": ((mode_dir / audio_file).exists() or (BASE_DIR / audio_file).exists())
                 if mode != "audiosum" else False,
        "report_path": str(mode_dir / report_file),
        "audio_path": str(mode_dir / audio_file),
    }
    payload["history"] = HISTORY[-10:]
    payload["key_set"] = bool(engine.OLLAMA_CLOUD_API_KEY.strip())
    return payload


@app.get("/api/steps_config")
def api_steps_config():
    """Workflow steps per mode for the frontend stepper (preset-aware)."""
    cfg = load_config()
    news_steps = news_steps_for(cfg)
    return {m: [{"n": n, "title": t, "desc": d, "agent": a}
                for n, t, d, a in steps]
            for m, steps in [("news", news_steps)]
            + [(m, s) for m, s in WORKFLOW_STEPS_BY_MODE.items() if m != "news"]}


@app.get("/api/presets")
def api_presets():
    """Topic preset catalog for the frontend dropdown."""
    return {k: {"label": p["label"], "icon": p["icon"],
                "prompt": p["prompt"], "whitelist": p["whitelist"],
                "region": p["region"], "financials": p["financials"],
                "agent_name": p["agent_name"]}
            for k, p in TOPIC_PRESETS.items()}


@app.get("/api/languages")
def api_languages():
    return {code: {"label": v["label"], "joe": v["joe"], "jane": v["jane"]}
            for code, v in LANGUAGES.items()}


@app.get("/api/report")
def api_report(mode: str = "news"):
    cfg = load_config()
    report_file, _audio = mode_artifacts(cfg, mode if mode in WORKFLOW_STEPS_BY_MODE else "news")
    mode_dir = engine.output_dir("audiosum" if mode == "audiosum" else mode)
    p = mode_dir / report_file
    if not p.exists():
        p = BASE_DIR / report_file  # legacy location
    if not p.exists():
        raise HTTPException(404, "report not generated yet")
    return Response(p.read_text(encoding="utf-8"), media_type="text/markdown")


@app.get("/api/audio")
def api_audio(download: bool = False, mode: str = "news"):
    cfg = load_config()
    _report, audio_file = mode_artifacts(cfg, mode if mode in WORKFLOW_STEPS_BY_MODE else "news")
    mode_dir = engine.output_dir(mode if mode in WORKFLOW_STEPS_BY_MODE else "news")
    p = mode_dir / audio_file
    if not p.exists():
        p = BASE_DIR / audio_file  # legacy location
    if not p.exists():
        raise HTTPException(404, "audio not generated yet")
    data = p.read_bytes()
    if download:
        return Response(data, media_type="audio/mpeg",
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"'})
    return Response(data, media_type="audio/mpeg")


@app.get("/api/voice_preview")
def api_voice_preview(voice: str, text: str = "Hello from the podcast studio!"):
    # accept alias (joe/jane), any engine-configured voice, or any edge-tts
    # voice name (e.g. ja-JP-KeitaNeural) for multi-language previews
    if voice == "joe":
        voice = engine.SPEAKERS[0]["voice"]
    elif voice == "jane":
        voice = (engine.SPEAKERS[1]["voice"] if len(engine.SPEAKERS) > 1
                 else engine.SPEAKERS[0]["voice"])
    try:
        data = preview_voice(voice, text)
    except Exception as e:
        raise HTTPException(500, f"TTS failed: {e}")
    return Response(data, media_type="audio/mpeg")



# ---------------------------------------------------------------------------
# HTML page (embedded)
# ---------------------------------------------------------------------------
def _page() -> str:
    steps_by_mode_json = json.dumps({
        m: [{"n": n, "title": t, "desc": d, "agent": a}
            for n, t, d, a in steps]
        for m, steps in WORKFLOW_STEPS_BY_MODE.items()})
    agents_json = json.dumps(AGENTS)
    return (_PAGE_TEMPLATE
            .replace("__STEPS__", steps_by_mode_json)
            .replace("__AGENTS__", agents_json))


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Voice Agent</title>
<style>
:root{
  --bg:#0f1420;--panel:#171e2e;--panel2:#1b2336;--line:#2a3550;
  --text:#e8edf7;--dim:#8b98b8;--accent:#5b8cff;
  --grey:#3a4358;--yellow:#e8b93e;--green:#3ecf8e;--red:#ef5b5b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:14px/1.5 "Segoe UI",system-ui,sans-serif;padding:20px}
h1{font-size:20px;margin-bottom:2px}
.sub{color:var(--dim);font-size:12px;margin-bottom:16px}
.badge{display:inline-block;background:var(--panel2);border:1px solid var(--line);
  color:var(--dim);border-radius:20px;padding:2px 10px;font-size:11px;margin-right:6px}

/* mode tabs */
.tabs{display:flex;gap:8px;margin-bottom:14px}
.tab{background:var(--panel2);border:1px solid var(--line);color:var(--dim);
  border-radius:8px;padding:8px 18px;font:inherit;font-weight:600;cursor:pointer;font-size:13px}
.tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.tab .tab-sub{display:block;font-size:10px;font-weight:400;opacity:.8}

/* recap input switcher (transcript vs audio) */
.seg-switch{display:flex;gap:6px;margin-bottom:10px}
.seg-switch button{background:var(--panel2);border:1px solid var(--line);color:var(--dim);
  border-radius:6px;padding:5px 12px;font:inherit;font-size:12px;cursor:pointer}
.seg-switch button.active{background:var(--panel);border-color:var(--accent);color:var(--text)}
.audio-drop{border:1px dashed var(--line);border-radius:8px;padding:12px;background:var(--panel2)}

/* now-working banner */
.now-working{display:flex;align-items:center;gap:8px;background:var(--panel2);
  border:1px solid var(--yellow);border-radius:8px;padding:6px 12px;margin-bottom:12px;
  font-size:13px}
.now-working .nw-icon{font-size:18px}
.now-working .nw-name{font-weight:700;color:var(--yellow)}
.now-working .nw-role{color:var(--dim);font-size:11px}
.now-working .nw-pulse{width:9px;height:9px;border-radius:50%;background:var(--yellow);
  margin-left:auto;animation:pulse 1.1s infinite}

/* stepper */
.stepper{display:flex;align-items:flex-start;gap:0;margin:18px 0 22px;overflow-x:auto;padding-bottom:6px}
.step{flex:1;min-width:96px;text-align:center;position:relative}
.step .dot{width:30px;height:30px;border-radius:50%;background:var(--grey);color:#0f1420;
  font-weight:700;display:flex;align-items:center;justify-content:center;margin:0 auto 6px;
  font-size:13px;transition:background .3s,border .3s}
.step .label{font-size:11px;color:var(--dim);margin-top:6px}
.step .agent{font-size:9px;color:var(--dim);opacity:.75;margin-top:1px;white-space:nowrap}
.step .time{font-size:10px;color:var(--dim);margin-top:2px}
.step:not(:last-child)::after{content:"";position:absolute;top:15px;left:calc(50% + 16px);
  right:calc(-50% + 16px);height:2px;background:var(--line)}
.step{position:relative}
.step.done .dot{background:var(--green)}
.step.running .dot{background:var(--yellow);animation:pulse 1.2s infinite}
.step.error .dot{background:var(--red)}
.step.running .label{color:var(--yellow)}
.step.done .label{color:var(--green)}
.step.error .label{color:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
.legend{display:flex;gap:14px;font-size:11px;color:var(--dim);margin-bottom:14px}
.legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:50%;
  margin-right:5px;vertical-align:-1px}
.legend .lg-idle::before{background:var(--grey)}
.legend .lg-run::before{background:var(--yellow)}
.legend .lg-done::before{background:var(--green)}
.legend .lg-err::before{background:var(--red)}

/* layout */
.grid{display:grid;grid-template-columns:380px 1fr;gap:16px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);margin-bottom:10px}
textarea,input[type=text],input[type=number],select{width:100%;background:var(--panel2);
  border:1px solid var(--line);color:var(--text);border-radius:6px;padding:8px;font:inherit}
textarea{min-height:70px;resize:vertical}
button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:9px 16px;
  font:inherit;font-weight:600;cursor:pointer}
button:disabled{opacity:.45;cursor:not-allowed}
button.ghost{background:var(--panel2);border:1px solid var(--line);color:var(--text)}
button.stop{background:var(--red)}
.row{display:flex;gap:8px;margin-top:10px}
.field{margin-bottom:10px}
.field label{display:block;font-size:11px;color:var(--dim);margin-bottom:4px}
details{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--panel2)}
details summary{cursor:pointer;color:var(--dim);font-size:12px}
.cfg-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.cfg-grid .wide{grid-column:1/-1}
.domains{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.domains .chip{background:var(--panel);border:1px solid var(--line);color:var(--dim);
  border-radius:14px;padding:3px 10px;font-size:11px}
.domains .chip button{background:none;border:none;color:var(--red);padding:0 0 0 6px;font-size:11px}
.add-dom{display:flex;gap:6px;margin-top:8px}
.add-dom input{flex:1}

/* log + results */
.log{background:#0b0f19;border:1px solid var(--line);border-radius:8px;padding:10px;
  height:220px;overflow-y:auto;font:12px/1.6 Consolas,monospace;color:#a8b6d8;white-space:pre-wrap}
.report{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:14px;
  max-height:340px;overflow-y:auto}
.report h1,.report h2,.report h3{margin:10px 0 6px}
.report p{margin:6px 0}
.report ul{margin:6px 0 6px 18px}
.agent-final{background:var(--panel2);border-left:3px solid var(--accent);border-radius:6px;
  padding:10px;margin-top:10px;color:var(--text)}
.audio{margin-top:10px}
audio{width:100%;margin-top:8px}
.dl{display:flex;gap:8px;margin-top:8px}
.status-pill{display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600}
.st-idle{background:var(--grey);color:#0f1420}
.st-running{background:var(--yellow);color:#0f1420;animation:pulse 1.2s infinite}
.st-done{background:var(--green);color:#0f1420}
.st-error{background:var(--red);color:#fff}
table.hist{width:100%;border-collapse:collapse;font-size:12px}
table.hist td,table.hist th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left}
table.hist th{color:var(--dim);font-weight:600}

/* hosts editor */
.host-row{display:grid;grid-template-columns:0.8fr 1.4fr 1.4fr;gap:6px;padding:8px;
  background:var(--panel);border:1px solid var(--line);border-radius:8px;margin-bottom:8px}
.host-row .field{margin-bottom:0}
.hosts-block label{font-weight:600}
</style>
</head>
<body>
<h1>AI Voice Agent</h1>
<div class="sub">
  <span class="badge" id="badge-model"></span>
  <span class="badge" id="badge-lang"></span>
  <span class="badge" id="badge-proxy"></span>
  <span class="badge" id="badge-key"></span>
</div>

<div id="now-working" class="now-working" style="display:none">
  <span class="nw-icon" id="nw-icon"></span>
  <span class="nw-name" id="nw-name"></span>
  <span class="nw-role" id="nw-role"></span>
  <span class="nw-pulse"></span>
</div>

<div class="tabs" id="mode-tabs">
  <button class="tab active" id="tab-news" onclick="switchMode('news')">� Research Agent
    <span class="tab-sub">web research &rarr; report + podcast</span></button>
  <button class="tab" id="tab-recap" onclick="switchMode('recap')">📋 Recap Agent
    <span class="tab-sub">transcript/audio &rarr; recap &amp; highlights</span></button>
</div>

<div class="stepper" id="stepper"></div>
<div class="legend">
  <span class="lg-idle">not started</span><span class="lg-run">running</span>
  <span class="lg-done">completed</span><span class="lg-err">error</span>
</div>

<div class="grid">
  <div>
    <div class="panel">
      <h2 id="input-title">Research prompt</h2>
      <div id="news-input">
        <div class="row" style="margin-bottom:8px">
          <label style="font-size:12px;color:var(--dim);margin-right:6px">Topic</label>
          <select id="cfg-preset" onchange="onPresetChange()" style="flex:1"></select>
        </div>
        <div class="field wide" id="custom-topic-row" style="display:none;margin-bottom:8px">
          <label>Your research topic (used as scope + prompt prefill)</label>
          <input type="text" id="cfg-custom-topic" placeholder="e.g. Electric vehicle news in Europe">
        </div>
        <textarea id="prompt">Research the latest AI news for NASDAQ-listed US companies</textarea>
        <div class="muted" id="preset-note" style="font-size:11px;margin-top:4px"></div>
      </div>
      <div id="recap-input" style="display:none">
        <div class="seg-switch">
          <button id="seg-text" class="active" onclick="switchRecapInput('text')">📄 Transcript text</button>
          <button id="seg-audio" onclick="switchRecapInput('audio')">🎵 Audio recording</button>
          <span id="seg-note" style="color:var(--dim);font-size:11px;margin-left:6px"></span>
        </div>
        <div id="recap-text-pane">
          <textarea id="transcript" style="min-height:180px"
            placeholder="Paste the meeting transcript here (Zoom/Teams export, notes, etc.)..."></textarea>
          <div class="row" style="margin-top:6px">
            <input type="file" id="transcript-file" accept=".txt,.md,.vtt,.srt,.docx"
              style="font-size:12px;color:var(--dim)">
            <button class="ghost" onclick="loadTranscriptFile()">Load file</button>
          </div>
        </div>
        <div id="recap-audio-pane" style="display:none">
          <div class="audio-drop" id="audio-drop">
            <input type="file" id="audio-file" accept=".mp3,.wav,.m4a,.flac,.ogg,.opus,.webm,.mp4,.aac"
              style="font-size:12px;color:var(--dim)">
            <div id="audio-chosen" style="font-size:12px;color:var(--dim);margin-top:6px">No audio selected — the recording is transcribed locally (faster-whisper), then summarized. No audio output is produced.</div>
          </div>
        </div>
      </div>
      <div class="row">
        <button id="btn-run" onclick="startRun()">Start</button>
        <button id="btn-stop" class="stop" onclick="stopRun()" disabled>Stop</button>
      </div>
      <div id="run-state" style="margin-top:8px;font-size:12px;color:var(--dim)"></div>
    </div>

    <div class="panel">
      <details>
        <summary>Configuration</summary>
        <div class="cfg-grid">
          <div class="field wide"><label>Model</label><input type="text" id="cfg-model"></div>
          <div class="field wide"><label>Report & podcast language</label>
            <select id="cfg-lang" onchange="onLanguageChange()"></select></div>
          <div class="field wide hosts-block">
            <label>Podcast format — hosts (1–4, name + voice + persona)</label>
            <div class="cfg-grid" style="margin-top:6px">
              <div class="field wide"><label>Host count</label>
                <select id="cfg-hostcount" onchange="onHostCountChange()">
                  <option value="1">1 — Solo anchor</option>
                  <option value="2" selected>2 — Duo (Joe + Jane)</option>
                  <option value="3">3 — Trio panel</option>
                  <option value="4">4 — Full panel</option>
                </select></div>
            </div>
            <div id="host-rows"></div>
            <div class="row">
              <button class="ghost" onclick="previewHost(0)">&#9654; Preview host 1</button>
              <button class="ghost" onclick="previewHost(1)" id="btn-prev2">&#9654; Preview host 2</button>
              <button class="ghost" onclick="previewHost(2)" id="btn-prev3">&#9654; Preview host 3</button>
              <button class="ghost" onclick="previewHost(3)" id="btn-prev4">&#9654; Preview host 4</button>
            </div>
          </div>
          <div class="field"><label>Max search results</label><input type="number" id="cfg-max" min="1" max="20"></div>
          <div class="field"><label>Freshness (timelimit)</label>
            <select id="cfg-tl"><option value="d">day</option><option value="w">week</option>
            <option value="m">month</option><option value="y">year</option></select></div>
          <div class="field"><label>Region</label><input type="text" id="cfg-region"></div>
          <div class="field"><label>Max auto-continue nudges</label><input type="number" id="cfg-nudge" min="0" max="30"></div>
          <div class="field hosts-legacy" style="display:none">
            <label>Joe voice (legacy)</label>
            <div style="display:flex;gap:6px"><input type="text" id="cfg-joe">
            <button class="ghost" onclick="preview('joe')">&#9654;</button></div></div>
          <div class="field hosts-legacy" style="display:none">
            <label>Jane voice (legacy)</label>
            <div style="display:flex;gap:6px"><input type="text" id="cfg-jane">
            <button class="ghost" onclick="preview('jane')">&#9654;</button></div></div>
          <div class="field"><label>Report filename</label><input type="text" id="cfg-report"></div>
          <div class="field"><label>Audio filename</label><input type="text" id="cfg-audio"></div>
          <div class="field"><label>Recap filename (Meeting tab)</label><input type="text" id="cfg-recap-report"></div>
          <div class="field"><label>Recap audio filename (Meeting tab)</label><input type="text" id="cfg-recap-audio"></div>
          <div class="field wide"><label>Whitelist domains</label>
            <div class="domains" id="dom-list"></div>
            <div class="add-dom"><input type="text" id="dom-new" placeholder="example.com">
            <button class="ghost" onclick="addDomain()">Add</button></div></div>
        </div>
        <div class="row">
          <button onclick="saveConfig()">Save config</button>
          <button class="ghost" onclick="resetConfig()">Reset to defaults</button>
        </div>
      </details>
    </div>

    <div class="panel">
      <h2>Run history</h2>
      <table class="hist"><thead><tr><th>Time</th><th>Task</th><th>Artifacts</th></tr></thead>
      <tbody id="hist-body"><tr><td colspan="3" style="color:var(--dim)">no runs yet</td></tr></tbody></table>
    </div>
  </div>

  <div>
    <div class="panel">
      <h2>Live log</h2>
      <div class="log" id="log">waiting for run...</div>
    </div>
    <div class="panel">
      <h2>Report</h2>
      <div class="report" id="report">No report yet. Start a run to generate one.</div>
    </div>
    <div class="panel">
      <h2>🎙 Generated audio</h2>
      <div class="audio" id="audio-box">No audio yet.</div>
      <div class="dl">
        <button class="ghost" id="dl-audio" disabled>Download MP3</button>
        <button class="ghost" onclick="downloadReport()" id="dl-report" disabled>Download report</button>
      </div>
    </div>
    <div class="panel" id="final-panel" style="display:none">
      <h2>Agent final message</h2>
      <div class="agent-final" id="agent-final"></div>
    </div>
  </div>
</div>

<script>
const STEPS_BY_MODE = __STEPS__;
const AGENTS = __AGENTS__;
let prevStates = {};
let MODE = 'news';
let STEPS = STEPS_BY_MODE.news;
let RECAP_INPUT = 'text';  // inside recap tab: 'text' | 'audio'
let UPLOADED_AUDIO = null; // server-side filename after /api/upload
let PRESETS = {};          // /api/presets cache
let PRESET_APPLYING = false; // guard against saveConfig during prefill

async function loadPresets(selected){
  PRESETS = await (await fetch('/api/presets')).json();
  const sel = document.getElementById('cfg-preset');
  sel.innerHTML = Object.entries(PRESETS).map(([k,v]) =>
    `<option value="${k}" ${k===selected?'selected':''}>${v.icon} ${v.label}</option>`).join('');
  onPresetChange(false);
}

function onPresetChange(applyPrompt=true){
  const key = document.getElementById('cfg-preset').value;
  const p = PRESETS[key] || {};
  const isCustom = key === 'custom';
  document.getElementById('custom-topic-row').style.display = isCustom ? '' : 'none';
  const note = [];
  if (p.financials) note.push('includes live stock data');
  else note.push('stock data off for this preset');
  if (p.whitelist && p.whitelist.length) note.push('sources: ' + p.whitelist.slice(0,3).join(', ') + (p.whitelist.length>3 ? ` +${p.whitelist.length-3} more` : ''));
  if (p.region) note.push('region: ' + p.region);
  document.getElementById('preset-note').textContent = note.join(' \u00b7 ');
  if (!applyPrompt || PRESET_APPLYING) return;
  PRESET_APPLYING = true;
  try {
    if (!isCustom && p.prompt) document.getElementById('prompt').value = p.prompt;
    if (isCustom){ document.getElementById('prompt').value = ''; document.getElementById('cfg-custom-topic').focus(); }
  } finally { PRESET_APPLYING = false; }
}

function currentPresetKey(){
  const sel = document.getElementById('cfg-preset');
  return sel ? sel.value : 'ai_nasdaq';
}

async function applyPresetConfig(){
  // persist the selected preset's whitelist/region into config.json so the
  // run + whitelist chips reflect it (prompt is sent per-run, not saved)
  const key = document.getElementById('cfg-preset').value;
  const p = PRESETS[key] || {};
  const body = { topic_preset: key, search_region: p.region || 'us-en' };
  if (key !== 'custom' && p.whitelist && p.whitelist.length) body.whitelist_domains = p.whitelist.slice();
  const cfg = await (await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  CURRENT_DOMAINS = cfg.whitelist_domains || [];
  renderDomains2(CURRENT_DOMAINS);
}

function switchRecapInput(which){
  RECAP_INPUT = which;
  document.getElementById('seg-text').classList.toggle('active', which==='text');
  document.getElementById('seg-audio').classList.toggle('active', which==='audio');
  document.getElementById('recap-text-pane').style.display = which==='text' ? '' : 'none';
  document.getElementById('recap-audio-pane').style.display = which==='audio' ? '' : 'none';
  document.getElementById('input-title').textContent = which==='audio' ? 'Audio recording' : 'Meeting transcript';
  document.getElementById('seg-note').textContent = which==='audio' ? 'text-only summary, no podcast' : 'recap + podcast';
}

async function uploadAudio(){
  const f = document.getElementById('audio-file').files[0];
  if (!f) { UPLOADED_AUDIO = null; document.getElementById('audio-chosen').textContent = 'No audio selected.'; return; }
  document.getElementById('audio-chosen').textContent = 'Uploading ' + f.name + ' ...';
  const r = await fetch('/api/upload?filename=' + encodeURIComponent(f.name), {method:'POST', body: f});
  if (!r.ok){ const e = await r.json(); document.getElementById('audio-chosen').textContent = 'Upload failed: ' + (e.detail||''); UPLOADED_AUDIO = null; return; }
  const j = await r.json();
  UPLOADED_AUDIO = j.file;
  document.getElementById('audio-chosen').textContent = `Ready: ${j.file} (${(j.size/1048576).toFixed(1)} MB)`;
}
document.getElementById('audio-file') && (document.getElementById('audio-file').onchange = () => uploadAudio());

function switchMode(m){
  if (MODE === m) return;
  MODE = m;
  STEPS = STEPS_BY_MODE[m];
  document.getElementById('tab-news').classList.toggle('active', m==='news');
  document.getElementById('tab-recap').classList.toggle('active', m==='recap');
  document.getElementById('news-input').style.display = m==='news' ? '' : 'none';
  document.getElementById('recap-input').style.display = m==='recap' ? '' : 'none';
  document.getElementById('input-title').textContent = m==='recap' ? (RECAP_INPUT==='audio' ? 'Audio recording' : 'Meeting transcript') : 'Research prompt';
  document.getElementById('stepper').dataset.built = '';  // force stepper rebuild
  renderStepper({});
}

function loadTranscriptFile(){
  const f = document.getElementById('transcript-file').files[0];
  if (!f) return alert('Choose a transcript file first (.txt/.md/.vtt/.srt/.docx)');
  const reader = new FileReader();
  reader.onload = e => {
    document.getElementById('transcript').value = e.target.result;
    document.getElementById('input-title').textContent = 'Meeting transcript (loaded: ' + f.name + ')';
  };
  reader.readAsText(f);
}

// ---- hosts state (1-4 hosts: name + voice + persona) ----
let HOSTS = [];
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function hostRowHtml(i){
  const h = HOSTS[i] || {name:'', voice:'', persona:''};
  return `<div class="host-row">
    <div class="field"><label>Host ${i+1} name</label>
      <input type="text" value="${esc(h.name)}" oninput="HOSTS[${i}].name=this.value" placeholder="Joe"></div>
    <div class="field"><label>Voice (edge-tts)</label>
      <input type="text" value="${esc(h.voice)}" oninput="HOSTS[${i}].voice=this.value" placeholder="en-US-GuyNeural"></div>
    <div class="field"><label>Persona</label>
      <input type="text" value="${esc(h.persona||'')}" oninput="HOSTS[${i}].persona=this.value" placeholder="enthusiastic host"></div>
  </div>`;
}
function renderHosts(){
  const n = parseInt(document.getElementById('cfg-hostcount').value)||2;
  if (HOSTS.length < n){
    const defaults = [['Joe','en-US-GuyNeural','the enthusiastic host who opens each segment'],
                      ['Jane','en-US-JennyNeural','the analytical co-host who adds depth and data'],
                      ['Ravi','en-IN-PrabhatNeural','the skeptical fact-checker who questions the hype'],
                      ['Mei','zh-CN-XiaoxiaoNeural','the market analyst focused on numbers']];
    for (let i = HOSTS.length; i < n; i++)
      HOSTS.push({name: defaults[i][0], voice: defaults[i][1], persona: defaults[i][2]});
  }
  HOSTS = HOSTS.slice(0, n);
  document.getElementById('host-rows').innerHTML =
    HOSTS.map((_,i)=>hostRowHtml(i)).join('');
  ['btn-prev2','btn-prev3','btn-prev4'].forEach((id,idx)=>{
    document.getElementById(id).style.display = (idx+2<=n)?'':'none';
  });
}
function onHostCountChange(){ renderHosts(); }
function collectHosts(){
  return HOSTS.slice(0, parseInt(document.getElementById('cfg-hostcount').value)||2)
    .map(h => ({name:(h.name||'').trim(), voice:(h.voice||'').trim(), persona:(h.persona||'').trim()}))
    .filter(h => h.name && h.voice);
}
async function previewHost(i){
  const h = HOSTS[i]; if (!h) return;
  const voice = (h.voice||'').trim(); if (!voice) return alert('Enter a voice for host '+(i+1));
  const name = (h.name||('Host '+(i+1))).trim();
  const text = `Hi, I am ${name}. ${h.persona||'Welcome to the show'}!`;
  const r = await fetch(`/api/voice_preview?voice=${encodeURIComponent(voice)}&text=${encodeURIComponent(text)}`);
  if (!r.ok){ alert('preview failed: '+(await r.json()).detail); return; }
  const blob = await r.blob(); new Audio(URL.createObjectURL(blob)).play();
}

function renderStepper(steps){
  const el = document.getElementById('stepper');
  const stepsKey = JSON.stringify(STEPS.map(s=>s.n)+':'+STEPS.map(s=>s.title).join(','));
  if (el.dataset.built !== stepsKey){
    el.innerHTML = STEPS.map(s => {
      const a = AGENTS[s.agent] || {};
      return `<div class="step" id="step-${s.n}" title="${s.desc} — ${a.name||''}">
         <div class="dot">${s.n}</div>
         <div class="label">${s.title}</div>
         <div class="agent">${a.icon||''} ${a.name||''}</div>
         <div class="time" id="time-${s.n}"></div>
       </div>`;}).join('');
    el.dataset.built = stepsKey;
  }
  STEPS.forEach(s => {
    const st = steps[s.n] || {state:'idle'};
    const div = document.getElementById(`step-${s.n}`);
    div.className = 'step ' + st.state;
    const t = document.getElementById(`time-${s.n}`);
    if (st.started){
      const end = st.ended || (st.state==='running' ? Date.now()/1000 : st.ended);
      const secs = Math.max(0, Math.round(end - st.started));
      t.textContent = st.started ? (secs+'s') : '';
    } else t.textContent = '';
  });
  const nw = document.getElementById('now-working');
  const cur = document.getElementById('current-agent-key');
  let runningAgent = null;
  STEPS.forEach(s => { const st = steps[s.n]; if (st && st.state==='running') runningAgent = s.agent; });
  const ca = (cur && cur.value) || runningAgent;
  if (ca){
    const a = AGENTS[ca] || {};
    nw.style.display = 'flex';
    document.getElementById('nw-icon').textContent = a.icon||'';
    document.getElementById('nw-name').textContent = a.name||ca;
    document.getElementById('nw-role').textContent = a.role||'';
  } else { nw.style.display = 'none'; }
}

async function poll(){
  try{
    const r = await fetch('/api/status'); const d = await r.json();
    renderStepper(d.steps);
    const curKey = d.current_agent;
    const cur = document.createElement('input'); cur.type='hidden'; cur.id='current-agent-key';
    if (!document.getElementById('current-agent-key')) document.body.appendChild(cur);
    document.getElementById('current-agent-key').value = d.running ? (curKey||'') : '';
    document.getElementById('btn-run').disabled = d.running;
    document.getElementById('btn-stop').disabled = !d.running;
    document.getElementById('run-state').textContent =
      d.running ? `running (nudges: ${d.nudges})` : (d.finished_at ? 'finished' : 'idle');
    const log = document.getElementById('log');
    if (d.log.length){ log.textContent = d.log.map(l=>`[${l.ts}] ${l.text}`).join('\\n'); log.scrollTop = log.scrollHeight; }
    if (d.agent_text){
      const fp = document.getElementById('final-panel');
      fp.style.display='block'; document.getElementById('agent-final').textContent = d.agent_text;
    }
    // follow the server's run mode only while a run is active; when idle the
    // user's selected tab stays authoritative (server keeps the last mode)
    if (d.running && d.mode && STEPS_BY_MODE[d.mode] && d.mode !== MODE){
      MODE = d.mode; STEPS = STEPS_BY_MODE[d.mode];
      document.getElementById('tab-news').classList.toggle('active', MODE==='news');
      document.getElementById('tab-recap').classList.toggle('active', MODE==='recap');
      document.getElementById('news-input').style.display = MODE==='news' ? '' : 'none';
      document.getElementById('recap-input').style.display = MODE==='recap' ? '' : 'none';
      document.getElementById('input-title').textContent = MODE==='recap' ? 'Meeting transcript' : 'Research prompt';
      document.getElementById('stepper').dataset.built = '';
      renderStepper({});
    }
    const am = d.running ? (d.mode || 'news') : MODE;
    if (d.artifacts.report){
      const r = await fetch('/api/report?mode='+am); if (r.ok){ renderMarkdown(await r.text()); document.getElementById('dl-report').disabled=false; }
      else { document.getElementById('report').textContent = am==='recap' ? 'No recap yet for this mode.' : 'No report yet.'; }
    }
    if (d.artifacts.audio){
      document.getElementById('audio-box').innerHTML =
        `<audio controls src="/api/audio?mode=${am}&cb=${Date.now()}"></audio>`;
      document.getElementById('dl-audio').disabled = false;
      document.getElementById('dl-audio').onclick = () => location.href = '/api/audio?download=true&mode='+am;
    }
    if (d.history.length){
      document.getElementById('hist-body').innerHTML = d.history.slice().reverse().map(h =>
        `<tr><td>${h.ts}</td><td>${h.mode==='recap'?'🎙':'📰'} ${h.prompt}</td><td>${[h.report?'report':'',h.audio?'audio':''].filter(Boolean).join('+')||'-'}</td></tr>`).join('');
    }
  }catch(e){}
}

function renderMarkdown(md){
  // minimal markdown: headings, bold, lists, links, code
  let h = esc(md);
  h = h.replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>');
  h = h.replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>');
  h = h.replace(/\\*(.+?)\\*/g,'<i>$1</i>');
  h = h.replace(/^[-*] (.*)$/gm,'<li>$1</li>').replace(/(<li>[\\s\\S]*?<\\/li>)/g,'<ul>$1</ul>').replace(/<\\/ul>\\s*<ul>/g,'');
  h = h.replace(/`(.+?)`/g,'<code>$1</code>');
  h = h.replace(/\\[(.*?)\\]\\((.*?)\\)/g,'<a href="$2" target="_blank">$1</a>');
  h = h.replace(/\\n\\n/g,'<br><br>');
  document.getElementById('report').innerHTML = h;
}

async function startRun(){
  let body;
  if (MODE === 'recap' && RECAP_INPUT === 'audio'){
    if (!UPLOADED_AUDIO) return alert('Select an audio recording first');
    body = {
      mode: 'audiosum',
      prompt: 'Summarize the uploaded audio recording with key highlights.',
      audio_file: UPLOADED_AUDIO,
      language: document.getElementById('cfg-lang').value,
      whisper_model: 'small',
    };
  } else if (MODE === 'recap'){
    const transcript = document.getElementById('transcript').value.trim();
    if (!transcript) return alert('Paste a meeting transcript first (or load a file)');
    body = {
      mode: 'recap',
      prompt: 'Create a meeting recap podcast from the meeting transcript.',
      transcript,
      language: document.getElementById('cfg-lang').value,
      hosts: collectHosts(),
      joe_voice: (collectHosts()[0]||{}).voice || '',
      jane_voice: (collectHosts()[1]||{}).voice || (collectHosts()[0]||{}).voice || '',
    };
  } else {
    const prompt = document.getElementById('prompt').value.trim();
    if (!prompt) return alert('Enter a prompt first');
    body = {
      mode: 'news',
      prompt,
      topic_preset: document.getElementById('cfg-preset').value,
      custom_topic: document.getElementById('cfg-custom-topic') ? document.getElementById('cfg-custom-topic').value.trim() : '',
      language: document.getElementById('cfg-lang').value,
      hosts: collectHosts(),
      joe_voice: (collectHosts()[0]||{}).voice || '',
      jane_voice: (collectHosts()[1]||{}).voice || (collectHosts()[0]||{}).voice || '',
    };
    await applyPresetConfig();
  }
  document.getElementById('log').textContent = '';
  document.getElementById('report').textContent = 'Generating...';
  document.getElementById('audio-box').textContent = 'Waiting for audio...';
  document.getElementById('final-panel').style.display = 'none';
  const r = await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  if (!r.ok){ alert((await r.json()).detail || 'could not start'); }
}
function stopRun(){ fetch('/api/stop',{method:'POST'}); }
function downloadReport(){
  const m = MODE;
  fetch('/api/report?mode='+m).then(r=>r.text()).then(t=>{
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([t],{type:'text/markdown'}));
  const f = m==='recap' ? (document.getElementById('cfg-recap-report')?.value || 'meeting_recap.md')
                        : (document.getElementById('cfg-report').value || 'report.md');
  a.download = f.endsWith('.md')?f:f+'.md'; a.click();
});}

async function loadConfig(){
  const c = await (await fetch('/api/config')).json();
  document.getElementById('cfg-model').value = c.model;
  document.getElementById('cfg-max').value = c.search_max_results;
  document.getElementById('cfg-tl').value = c.search_timelimit;
  document.getElementById('cfg-region').value = c.search_region;
  document.getElementById('cfg-nudge').value = c.max_auto_continue;
  document.getElementById('cfg-joe').value = c.joe_voice;
  document.getElementById('cfg-jane').value = c.jane_voice;
  document.getElementById('cfg-report').value = c.report_file;
  document.getElementById('cfg-audio').value = c.audio_file;
  document.getElementById('cfg-recap-report').value = c.recap_report_file || 'meeting_recap.md';
  document.getElementById('cfg-recap-audio').value = c.recap_audio_file || 'meeting_recap.mp3';
  HOSTS = (c.hosts && c.hosts.length) ? JSON.parse(JSON.stringify(c.hosts)) : [];
  document.getElementById('cfg-hostcount').value = String(Math.min(4, Math.max(1, HOSTS.length || 2)));
  renderHosts();
  await loadLanguages(c.language);
  renderDomains(c.whitelist_domains);
}
let LANGS = {};
async function loadLanguages(selected){
  LANGS = await (await fetch('/api/languages')).json();
  const sel = document.getElementById('cfg-lang');
  sel.innerHTML = Object.entries(LANGS).map(([code,v]) =>
    `<option value="${code}" ${code===selected?'selected':''}>${v.label}</option>`).join('');
}
function onLanguageChange(){
  const lang = LANGS[document.getElementById('cfg-lang').value];
  if (lang){
    document.getElementById('cfg-joe').value = lang.joe;
    document.getElementById('cfg-jane').value = lang.jane;
    // native voices for the selected language: hosts 1/2 get the pair,
    // extra hosts get locale-matched voices if known, else keep theirs
    if (HOSTS[0]) HOSTS[0].voice = lang.joe;
    if (HOSTS[1]) HOSTS[1].voice = lang.jane;
    renderHosts();
  }
}
function renderDomains(domains){
  document.getElementById('dom-list').innerHTML = domains_cache(domains);
}
function domains_cache(domains){
  return (domains||[]).map((d,i)=>`<span class="chip">${d}<button onclick="delDomain(${i})">&times;</button></span>`).join('');
}
let CURRENT_DOMAINS = [];
function renderDomains2(list){ CURRENT_DOMAINS = list; document.getElementById('dom-list').innerHTML =
  (list||[]).map((d,i)=>`<span class="chip">${d}<button onclick="delDomain(${i})">&times;</button></span>`).join(''); }
function delDomain(i){ CURRENT_DOMAINS.splice(i,1); renderDomains2(CURRENT_DOMAINS); }
function renderDomains2(list){ document.getElementById('dom-list').innerHTML =
  (list||[]).map((d,i)=>`<span class="chip">${d}<button onclick="delDomain(${i})">&times;</button></span>`).join(''); }
function addDomain(){ const v = document.getElementById('dom-new').value.trim();
  if (v && !CURRENT_DOMAINS.includes(v)){ CURRENT_DOMAINS.push(v); renderDomains2(CURRENT_DOMAINS);}
  document.getElementById('dom-new').value=''; }
async function saveConfig(){
  const body = {
    model: document.getElementById('cfg-model').value.trim(),
    language: document.getElementById('cfg-lang').value,
    search_max_results: parseInt(document.getElementById('cfg-max').value)||8,
    search_timelimit: document.getElementById('cfg-tl').value,
    search_region: document.getElementById('cfg-region').value.trim()||'us-en',
    max_auto_continue: parseInt(document.getElementById('cfg-nudge').value)||10,
    joe_voice: (collectHosts()[0]||{}).voice || '',
    jane_voice: (collectHosts()[1]||{}).voice || (collectHosts()[0]||{}).voice || '',
    report_file: document.getElementById('cfg-report').value.trim()||'ai_research_report.md',
    audio_file: document.getElementById('cfg-audio').value.trim()||'ai_today_podcast.mp3',
    recap_report_file: document.getElementById('cfg-recap-report').value.trim()||'meeting_recap.md',
    recap_audio_file: document.getElementById('cfg-recap-audio').value.trim()||'meeting_recap.mp3',
    hosts: collectHosts(),
    whitelist_domains: CURRENT_DOMAINS,
  };
  const cfg = await (await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  renderDomains2(cfg.whitelist_domains);
  document.getElementById('badge-model').textContent = 'model: '+cfg.model;
  const langLabel = (await (await fetch('/api/languages')).json())[cfg.language]?.label || cfg.language;
  document.getElementById('badge-lang').textContent = 'language: '+langLabel;
  alert('config saved');
}
async function resetConfig(){
  if(!confirm('Reset config to defaults?')) return;
  const d = DEFAULTS;
  await saveConfigBody(d);
  await loadConfig();
}
const DEFAULTS = {model:'openai/gpt-oss:120b',search_max_results:8,search_timelimit:'w',
  search_region:'us-en',max_auto_continue:10,joe_voice:'en-US-GuyNeural',
  jane_voice:'en-US-JennyNeural',report_file:'ai_research_report.md',
  audio_file:'ai_today_podcast.mp3',whitelist_domains:['techcrunch.com','venturebeat.com',
  'theverge.com','technologyreview.com','arstechnica.com'],
  hosts:[{name:'Joe',voice:'en-US-GuyNeural',persona:'the enthusiastic host who opens each segment'},
         {name:'Jane',voice:'en-US-JennyNeural',persona:'the analytical co-host who adds depth and data'}]};
async function saveConfigBody(body){
  const cfg = await (await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  renderDomains2(cfg.whitelist_domains);
}
async function preview(which){
  const voice = which==='joe' ? document.getElementById('cfg-joe').value : document.getElementById('cfg-jane').value;
  const text = which==='joe' ? 'Hi, I am Joe, your enthusiastic host!' : 'And I am Jane, the analytical one. Let us dive in!';
  const r = await fetch(`/api/voice/preview?voice=${which}&text=${encodeURIComponent(text)}`);
  if (!r.ok){ alert('preview failed: '+(await r.json()).detail); return; }
  const blob = await r.blob(); new Audio(URL.createObjectURL(blob)).play();
}

setInterval(()=>{ poll(); }, 1500);
poll(); loadConfig();
(async()=>{ const c = await (await fetch('/api/config')).json();
  await loadPresets(c.topic_preset || 'ai_nasdaq');
  document.getElementById('cfg-custom-topic').value = c.custom_topic || '';
  document.getElementById('badge-model').textContent = 'model: '+c.model;
  const langLabel = (await (await fetch('/api/languages')).json())[c.language]?.label || c.language;
  document.getElementById('badge-lang').textContent = 'language: '+langLabel;
  const s = await (await fetch('/api/status')).json();
  document.getElementById('badge-proxy').textContent = 'proxy: 127.0.0.1:11435';
  document.getElementById('badge-key').textContent = s.key_set ? 'api key: set' : 'api key: MISSING';
})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Extra voice-preview endpoint path alias (used by the page JS)
# ---------------------------------------------------------------------------
@app.get("/api/voice/preview")
def api_voice_preview_alias(voice: str, text: str = "Hello!"):
    return api_voice_preview(voice=voice, text=text)


if __name__ == "__main__":
    import uvicorn
    print(f"Podcast Agent UI on http://127.0.0.1:{UI_PORT}")
    # Run uvicorn on a BACKGROUND thread, not the main thread: faster-whisper
    # (ctranslate2) deadlocks its thread pool when the Proactor event loop
    # owns the main thread. With the loop parked on a worker thread the
    # transcription path works in-process (~30s for a 36s clip).
    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=UI_PORT,
                                   log_level="warning"),
        daemon=True,
    )
    server_thread.start()
    try:
        while True:
            time.sleep(3600)  # idle main thread keeps the process alive
    except KeyboardInterrupt:
        print("\nBye.")