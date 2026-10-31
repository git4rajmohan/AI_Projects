# Manual Test Plan

All commands use `.venv\Scripts\python.exe`. For local tests set `ALLOW_LOCAL_AGENTS=true`
and start the worker first: `python worker.py`.

## Test A — Manual Agent Card URL

1. `python remote_agents_cli.py discover http://127.0.0.1:9999/.well-known/agent-card.json`
2. Expect: name, skills, endpoint, protocol displayed.
3. Expect staged statuses with `Task execution: NOT TESTED` — a fetched card is
   never shown as a successful task connection.

## Test B — Remote task

1. `python remote_agents_cli.py save <card-url>` then `python remote_agents_cli.py task <id> "harmless question"`
2. Expect: task state shown, result text, and `[<agent name>] task <id>: COMPLETED` attribution.
3. `python remote_agents_cli.py history <id>` shows the run.

## Test C — Unavailable agent

1. `python remote_agents_cli.py discover https://offline.invalid/.well-known/agent-card.json`
2. Expect: `ERROR: request failed ...` / DNS error; app exits cleanly and remains usable.

## Test D — Non-A2A endpoint

1. `python remote_agents_cli.py discover https://example.com/`
2. Expect: "This endpoint is not a compatible A2A endpoint..." or a JSON/HTTP error —
   never treated as an agent.

## Test E — Authentication

1. Point at an agent whose card advertises auth; `Authentication: REQUIRED (...)` appears.
2. Without a token: expect clear `RemoteAuthError` (unauthorized).
3. With a wrong token (`$env:A2A_BEARER_TOKEN="bad"`): same clear error.
4. With the right token: task completes.
5. Verify no token in output or `agents.db` (`PRAGMA table_info` has no token column;
   log redaction masks Authorization headers).

## Public smoke test (optional, excluded from automated suite)

`python remote_agents_cli.py search directory` then task the chosen agent.
Last verified publicly: see README "Public agent test report".
