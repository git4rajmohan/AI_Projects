# Current Architecture (baseline two-agent demo)

## Stack

- Python 3.11.9, all deps in `.venv` (see `requirements.txt`)
- **a2a-sdk 1.3.0** (`[http-server]` extra) — proto-based types (`a2a.types` = `a2a_pb2`), A2A protocol version 1.0
- Transport: JSON-RPC over HTTP (SSE streaming supported)
- LLM: Ollama Cloud via `.env` (`OLLAMA_HOST=https://ollama.com`, `OLLAMA_MODEL=gpt-oss:120b`, bearer `OLLAMA_API_KEY`)

## Components

| File | Role |
|------|------|
| `smoke_test.py` | `ask(prompt)` — one sync httpx call to Ollama Cloud chat API; also a standalone env smoke test |
| `worker.py` | Agent B: FastAPI app serving agent card at `/.well-known/agent-card.json` + JSON-RPC A2A endpoint at `/` on `127.0.0.1:9999`. `WorkerExecutor` enqueues a Task, calls Ollama, completes/fails the task |
| `coordinator.py` | Agent A: `create_client(url)` resolves the card, `send_message` streams responses, returns last text chunk |
| `demo.py` | E2E check: spawns worker subprocess, waits for card endpoint, delegates "pong" task, asserts answer |

## Flow

```text
coordinator.delegate(text)
  -> resolve agent card (GET /.well-known/agent-card.json)
  -> JSON-RPC message/send (streaming)
       worker: enqueue Task -> start_work -> Ollama Cloud -> complete(answer)
  -> stream responses -> final text returned
```

## SDK notes (v1.3.0 specifics)

- `AgentCard` requires `supported_interfaces[].protocol_version` (`PROTOCOL_VERSION_CURRENT = "1.0"`)
- Executor must enqueue a full `Task` (`new_task_from_user_message`) before status updates
- Server app built with `add_a2a_routes_to_fastapi(app, agent_card_routes=..., jsonrpc_routes=...)`
- Client: `await create_client(url)` is async; `Client` is an async context manager
- Text helpers: `a2a.helpers.new_text_message`, `get_stream_response_text`

## Run commands

```powershell
.venv\Scripts\python.exe smoke_test.py    # Ollama Cloud connectivity
.venv\Scripts\python.exe demo.py          # full two-agent round-trip
.venv\Scripts\python.exe worker.py        # run Agent B standalone
.venv\Scripts\python.exe coordinator.py "question"   # Agent A against running worker
```

Last verified: 2026-10-31 — `demo.py` → `demo OK - worker answered: 'pong'`
