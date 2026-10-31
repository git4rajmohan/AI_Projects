Languages: **English** | [日本語](README.ja.md)

# Agent2Agent Explorer — Remote A2A Agent Discovery, Validation & Delegation

**From a public agent registry to a completed cross-organization task — nothing trusted until a real task completes.**

[Portfolio](../../README.md) | [User guide](A2A_Explorer_Userguide.html)

A Python A2A client/explorer that discovers, validates, and delegates tasks to
**independently hosted third-party A2A agents** — plus a local two-agent demo.
Built on `a2a-sdk 1.3.0`; the local agents answer via **Ollama Cloud**.

## Demo Video
[![Agent2AgentExplorerDemo](https://img.youtube.com/vi/qcHyCxMbgLI/0.jpg)](https://youtu.be/qcHyCxMbgLI)

## Why this project exists

Calling *someone else's* agent is nothing like calling your own: you don't know its
address, what it can do, whether it speaks your protocol, whether it wants
credentials — or whether the thing at that URL is even an agent at all and not just
a webpage or a REST API. Pointing code at a pasted URL and hoping is how integrations
break. The Agent2Agent Explorer is that first meeting, handled properly: **the
directory finds candidates, the Agent Card advertises, the validator proves — and
only the remote agent's own completed task counts as interoperability. A web page
answering 200 OK proves nothing.**

## What it demonstrates

- **Staged validation, never in bulk** — five independent checks with separate
  pass/fail badges: Card · Protocol · Endpoint · Authentication · Task execution.
  A valid card with a dead endpoint reads exactly like that; `task_ready` requires
  protocol *and* endpoint to pass, and "Task execution" only turns green from a real
  completed task.
- **Real registry discovery** — a2aregistry.org adapter built on its verified public
  API (`GET /api/agents`, per-agent detail resolution, client-side filtering, no
  scraping, no guessed paths). Paste-a-URL is the always-available fallback; even
  registry *web-page* links resolve to the real card automatically.
- **SDK first, always** — cards parse through `a2a.parse_agent_card`, tasks through
  SDK `ClientFactory`; the app invents no protocol messages and no registry endpoints.
- **Task lifecycle you can watch** — `SUBMITTED → WORKING → COMPLETED` (or FAILED /
  CANCELED / REJECTED / TIMEOUT), streaming when both sides advertise it, polling
  with a hard timeout otherwise; message-only replies are a first-class labeled case.
- **Deterministic routing + parallel delegation** — the coordinator routes tasks by
  word-overlap over *advertised skills* and requires explicit user confirmation
  before sending (the LLM never invents or picks URLs); `parallel` delegates the
  same task to two explicitly saved agents with per-agent attribution.
- **Untrusted-output discipline** — remote results displayed verbatim with
  attribution, never executed; artifacts listed but never auto-downloaded; x402-style
  paid-tool offers detected, warned about, never paid.

## Architecture

```text
LOCAL COORDINATOR
      | discovers
      v
PUBLIC AGENT DIRECTORY (a2aregistry.org, verified API)
      | returns candidate Agent Card URL
      v
REMOTE AGENT CARD  -- advertises endpoint + skills + auth
      v
REMOTE A2A ENDPOINT (HTTPS, SSRF-guarded, zero redirects)
      | task request / task result
      v
THIRD-PARTY AGENT  -> attributed result back to the LOCAL COORDINATOR
```

Every concept owns one file; the app is glue around the official `a2a-sdk 1.3.0`.
The Streamlit page (`webui.py`) and the CLIs (`remote_agents_cli.py`,
`coordinator.py`) call the same pipeline functions. See
[docs/remote_agent_architecture.md](docs/remote_agent_architecture.md).

**Stack:** Python 3.11+ · a2a-sdk 1.3.0 (`[http-server]` extra) · JSON-RPC + HTTP+JSON
transports · Streamlit · FastAPI · httpx · SQLite · Ollama Cloud (`gpt-oss:120b`) ·
pytest + pytest-asyncio

## Run locally (Windows PowerShell)

From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env: OLLAMA_API_KEY from https://ollama.com/settings/keys

# offline proof: LLM connectivity + local two-agent round-trip
.\.venv\Scripts\python.exe smoke_test.py
.\.venv\Scripts\python.exe demo.py

# the explorer (recommended)
.\.venv\Scripts\python.exe -m streamlit run webui.py
#    -> http://localhost:8511 — Discover -> Save -> Send Task -> Saved Agents

# same journey from the command line
.\.venv\Scripts\python.exe remote_agents_cli.py search <query>        # public registry
.\.venv\Scripts\python.exe remote_agents_cli.py discover <card-url>   # card + staged validation
.\.venv\Scripts\python.exe remote_agents_cli.py save <card-url>
.\.venv\Scripts\python.exe remote_agents_cli.py list
.\.venv\Scripts\python.exe remote_agents_cli.py task <id|card-url> "your question"
.\.venv\Scripts\python.exe coordinator.py remote "echo hello"         # skill match + confirmation
.\.venv\Scripts\python.exe coordinator.py parallel 1 2 "your question" # parallel delegation
```

For the **local** worker agent only, set `ALLOW_LOCAL_AGENTS="true"` in its terminal
first; public third-party agents work with zero extra config.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q   # 64 passed
```

The suite is fully offline: mocks for SSRF/DNS/registry responses plus local
same-SDK A2A test servers (including a bearer-protected one). No internet required.
Covers SSRF blocking (private/loopback/metadata IPs, redirects), card schema
validation, staged endpoint checks, task lifecycle, credential isolation and log
redaction, deterministic routing and parallel delegation.

## Public agent test report (real third-party interoperability)

| | |
|---|---|
| Agent | **Swarmnest** (swarmnest.ai, operated by Swarmnest) |
| Found via | `a2aregistry.org` public API (`GET /api/agents`) |
| Agent Card URL | `https://swarmnest.ai/.well-known/agent-card.json` |
| Tested on | 2026-10-31 (JST) |
| Authentication | none required |
| Task sent | "MCP server for Postgres" (its advertised `search-directory` skill) |
| Outcome | **COMPLETED** — returned a text summary + structured JSON (23 matches, top 5 with links) |

The validation pipeline on that card: `Agent Card: VALID / Protocol: SUPPORTED /
Endpoint: REACHABLE / Authentication: NONE REQUIRED`, then a real task completed.
Also verified 2026-10-31: **parallel delegation** to two independent public agents
(Swarmnest + Public Adjusters Directory, publicadjusters.fyi) — both COMPLETED in
one `coordinator.py parallel` run with per-agent attribution.
Public agents can go offline or change terms; this test is manual and excluded
from the automated suite.

## Security notes

- Every outbound URL passes SSRF validation before one byte leaves the machine:
  HTTPS enforced, DNS resolved, loopback/private/link-local/cloud-metadata IPs
  blocked (`ip.is_global`), zero redirects, response size capped, optional domain
  allowlist. `ALLOW_LOCAL_AGENTS=true` is the only door for localhost — dev/tests only.
- Bearer tokens (for agents that require auth) live only in the `A2A_BEARER_TOKEN`
  environment variable for the session or the UI's password field — never persisted,
  never logged (global log-record redaction), never passed on argv, per-call isolated.
- Remote agent output is untrusted: displayed verbatim with attribution, never
  executed, never treated as instructions.
- SQLite stores agent metadata and task history only — never credentials (no
  token/secret/password column exists; enforced by a test).

## Docs

- [docs/current_architecture.md](docs/current_architecture.md) — baseline two-agent demo
- [docs/remote_agent_architecture.md](docs/remote_agent_architecture.md) — remote explorer design + security boundaries
- [docs/manual_test_plan.md](docs/manual_test_plan.md) — manual tests A–E
- [A2A_Explorer_Userguide.html](A2A_Explorer_Userguide.html) — full illustrated guide (Elevator Pitch / Non-Technical / Technical / Glossary)

## Project layout

| Path | Purpose |
|---|---|
| [webui.py](webui.py) | Streamlit UI: Discover · Send Task · Saved Agents tabs |
| [remote_agents_cli.py](remote_agents_cli.py) | CLI for the same screens: search/discover/save/list/trust/refresh/task/history |
| [coordinator.py](coordinator.py) | Local demo client + remote delegation (deterministic routing, confirmation, parallel) |
| [worker.py](worker.py) / [demo.py](demo.py) | Local A2A server (Agent B) + end-to-end two-agent check |
| [discover.py](discover.py) / [smoke_test.py](smoke_test.py) | Thin discovery CLI / Ollama Cloud connectivity check |
| [remote_agents/](remote_agents/) | url_safety · config · card_fetcher · card_validator · endpoint_validator · remote_client · agent_store · log_redaction |
| [directories/](directories/) | Registry adapter (a2aregistry.org) + manual-URL provider |
| [tests/](tests/) | 64 offline pytest tests |
| [A2A_Explorer_Userguide.html](A2A_Explorer_Userguide.html) | Standalone illustrated guide; download and open in a browser |

## AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation decisions, testing, debugging and validation were reviewed and refined during development.
