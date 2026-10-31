# Remote Agent Architecture

## Module map

```text
remote_agents/
  config.py             A2A_* settings from .env (frozen dataclass)
  url_safety.py         SSRF guard: validate_url() before EVERY outbound request
  card_fetcher.py       fetch_card_json(): HTTPS, no redirects, size cap
  card_validator.py     validate_card(): SDK parse + required fields; summarize_card()
  endpoint_validator.py select_interface() + check_endpoint() -> staged EndpointReport
  remote_client.py      send_task()/cancel_task(): SDK client, streaming + polling,
                        timeouts, bearer auth, TaskResult (text/data/artifact metadata)
  agent_store.py        SQLite: remote_agents + agent_task_history (no credentials)
  log_redaction.py      log-record factory shim: bearer/authorization never logged
directories/
  base.py               AgentDirectoryProvider + AgentCandidate
  manual_url.py         manual card-URL fallback (always available)
  registry_provider.py  a2aregistry.org adapter (verified API, client-side filter)
coordinator.py          local demo delegation + remote: match_route/delegate_remote/present
remote_agents_cli.py    Remote Agents page: search/discover/save/list/trust/refresh/task/history
discover.py             thin discovery CLI (card + staged validation)
```

## Flow

```text
user query
  -> directory provider (registry search or manual URL)
  -> card_fetcher (SSRF check, HTTPS, size cap)
  -> card_validator (SDK schema)
  -> endpoint_validator (staged: card / protocol / endpoint / auth)
  -> remote_client.send_task (SDK client, advertised endpoint only)
  -> TaskResult -> coordinator.present (attributed, untrusted-verbatim)
  -> agent_store (metadata + history; never tokens)
```

## Security boundaries

- `validate_url()` runs before every fetch: HTTPS required, loopback/private/
  link-local/metadata blocked (`ip.is_global`), zero redirects, optional allowlist.
  `ALLOW_LOCAL_AGENTS=true` permits loopback only (dev/tests).
- Bearer tokens: `A2A_BEARER_TOKEN` env or per-call parameter; held only in a
  per-call httpx client header; never persisted, never logged (global redaction),
  never cross-origin (redirects disabled).
- Remote output is untrusted data: displayed verbatim with attribution, never
  executed, artifacts never auto-downloaded.
- Endpoints come only from validated Agent Cards — no URL guessing, no LLM-chosen URLs,
  deterministic skill routing with mandatory user confirmation.

## Task lifecycle handling

SUBMITTED -> WORKING -> COMPLETED | FAILED | CANCELED | REJECTED
- streaming when both sides support it, else polling (`A2A_POLL_INTERVAL_SECONDS`)
- hard stop at `A2A_TASK_TIMEOUT_SECONDS` -> state TIMEOUT
- message-only replies (no Task object) are treated as COMPLETED
- cancel_task() available where the remote supports it
