# Research Voice Agent — AI Research-to-Podcast Pipeline

> A multimodal/voice pipeline: research or transcripts are turned into a producer report, then a conversational script, then speech via TTS into an MP3.

## What This Project Demonstrates

- Speech-to-text (faster-whisper) and text-to-speech (edge-tts)
- Agentic research with web search
- Transcript summarization and report generation
- Conversational script generation and audio output

## Why This Project Exists

Demonstrates a full multimodal/voice AI pipeline — research, script generation and speech synthesis — rather than text-only LLM output.

## Architecture

```text
Research / Transcript
        ↓
Producer Agent
        ↓
Research Report
        ↓
Podcaster Agent
        ↓
Conversational Script
        ↓
TTS
        ↓
MP3
```

## Workflow

*To be verified from code.*

## Technology Stack

| Area | Technology |
|---|---|
| LLM | Ollama Cloud (gpt-oss:120b) via LiteLLM |
| AI Framework | Google ADK |
| Backend | FastAPI |
| Speech-to-Text | faster-whisper |
| Text-to-Speech | edge-tts |
| Search | DuckDuckGo (ddgs), yfinance |
| Config | python-dotenv, config.json |

*To be verified against the project's requirements files.*

**Modes:** AI News · Meeting Recap · Audio Summary

## Demo

*Screenshots/demo assets to be added when project code is copied into this repository.*

## How to Run

*To be verified from the project's actual installation and execution instructions.*

## Key AI Engineering Concepts

- Multimodal/voice AI pipeline
- Producer/podcaster agent handoff
- Source-domain whitelist & freshness guardrails

## Safety / Reliability

- Source-domain whitelist
- Freshness callback
- Process log & UI step tracker

## Testing / Evaluation

*To be verified.*

## How This Project Differs

Multimodal/voice AI pipeline rather than text-only AI.

## AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation decisions, testing, debugging and validation were reviewed and refined during development.