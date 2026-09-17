# Plan: E-Commerce Return & Fraud Prevention Agent (LangGraph + FastAPI)

Build the `return-agent/` service per Instructions.md: a LangGraph state machine with cyclical
photo-proof loop, deterministic fraud/fee rules, an Ollama-cloud-backed LLM node for return-reason
classification, SQLite-checkpointed human-in-the-loop `interrupt()` gate for refunds > $200, and a
FastAPI layer to start/approve/reject/inspect runs. Delivered as 7 independently testable phases.

## Decisions (confirmed with user)
- Fraud logic: mock heuristics (return velocity for customer, high-value + no-photo combo).
- Shipping fee: damaged/defective = $0.00; buyer's remorse = flat $5.99.
- LLM: real call via `langchain-ollama` `ChatOllama` pointed at Ollama Cloud, auth via `OLLAMA_API_KEY` env var. Used only for classifying free-text return reason into `damaged_defective` / `buyer_remorse`.
- API surface: `POST /returns`, `POST /returns/{thread_id}/approve`, `POST /returns/{thread_id}/reject`, `GET /returns/{thread_id}`.
- Photo proof loop: request carries `photo_provided: bool` (+ optional `photo_url`); if item is damaged/defective and no photo, graph calls `interrupt()`; client resubmits via a dedicated resume call which loops back to the same check node (bounded retries, default max 3).
- Checkpointer: `langgraph-checkpoint-sqlite` `SqliteSaver` (per instructions' mandate), DB file `checkpoints.sqlite`.
- Approve/reject payload: `{"manager_note": Optional[str]}`, resumes via `Command(resume={"decision": "approve"|"reject", "manager_note": ...})`.
- Fraud/interrupt thresholds (defaults, adjustable): refund > $200.00 OR fraud_score >= 0.7 → human approval gate. Fraud heuristic: `+0.4` if customer has ≥3 returns in trailing 30 days (mock DB lookup), `+0.4` if damaged claim with no photo after max retries exhausted, `+0.3` if refund_amount > $500.

## Steps / Phases

### Phase 0 — Project Scaffolding
*No dependencies. Purely file/dir creation — verify by directory listing + `pip install` succeeding.*
- [x] Create `return-agent/` root with subfolders `app/`, `tests/`.
- [x] Create empty `app/__init__.py`.
- [x] Create `requirements.txt`: `langgraph`, `langgraph-checkpoint-sqlite`, `langchain-core`, `langchain-ollama`, `fastapi`, `uvicorn`, `pydantic>=2`, `python-dotenv`, `pytest`, `pytest-asyncio`, `httpx`.
- [x] Create `.env.example`: `OLLAMA_API_KEY=`, `OLLAMA_MODEL=`, `OLLAMA_BASE_URL=https://ollama.com`, `SQLITE_DB_PATH=./checkpoints.sqlite`, `HIGH_VALUE_THRESHOLD=200.00`, `FRAUD_SCORE_THRESHOLD=0.7`, `MAX_PHOTO_RETRIES=3`.
- [x] Create stub `README.md` with setup + run instructions (fleshed out fully in Phase 6).
- **Verification:** `pip install -r requirements.txt` succeeds in a fresh venv; directory tree matches Instructions.md §3. ✅ (venv created at project root `.venv`, Python 3.11.9)

### Phase 1 — Config & Schemas
*Depends on Phase 0.*
- [x] `app/config.py`: `Settings` (pydantic `BaseSettings`) loading all `.env` vars listed above with sane defaults; a module-level `get_settings()` singleton.
- [x] `app/schemas.py`:
  - `ItemCondition` enum: `damaged_defective`, `buyer_remorse`, `unknown`.
  - `ReturnStatus` enum: `pending`, `awaiting_photo`, `awaiting_approval`, `approved`, `rejected`, `completed`, `denied_policy`.
  - `ReturnState` (TypedDict, used as LangGraph state): `order_id`, `customer_id`, `item_id`, `reason_text`, `photo_provided`, `photo_url`, `photo_retry_count`, `item_condition`, `order_date`, `item_value`, `shipping_fee`, `refund_amount`, `fraud_score`, `fraud_flags` (list[str]), `status`, `manager_note`, `decision_log` (list[str] audit trail).
  - API contracts: `ReturnRequest` (order_id, item_id, reason_text, photo_provided, photo_url optional), `ReturnResponse` (thread_id, status, message, next_action optional), `ApprovalRequest` (manager_note optional), `PhotoResubmitRequest` (photo_provided, photo_url optional).
- [x] Unit test `tests/test_schemas.py`: instantiate each model with valid/invalid data, assert `ValidationError` raised for bad enum values and missing required fields.
- **Verification:** `pytest tests/test_schemas.py -v` all green. ✅ (25 passed, venv `d:\...\.venv` Python 3.11.9)

### Phase 2 — Mock Services (Order DB, Payment Gateway, Fraud Heuristics)
*Depends on Phase 1. Independently testable business logic, no LangGraph/FastAPI involved.*
- [x] `app/services.py`:
  - `MOCK_ORDERS` in-memory dict seeded with ≥5 sample orders (varying `order_date` — some >30 days old, some fresh; varying `item_value`).
  - `MOCK_CUSTOMER_RETURN_HISTORY` dict: customer_id → list of past return timestamps (seed one customer with 3+ returns in last 30 days to trigger fraud path).
  - `get_order(order_id) -> Optional[dict]`.
  - `is_within_return_window(order_date, window_days=30) -> bool`.
  - `calculate_shipping_fee(condition: ItemCondition) -> float` ($0.00 vs $5.99 per Decisions).
  - `compute_fraud_score(customer_id, refund_amount, photo_provided) -> tuple[float, list[str]]` implementing the heuristic weights from Decisions.
  - `process_refund(order_id, amount) -> dict` (mock payment gateway, always succeeds, returns a fake transaction id).
- [x] `tests/test_services.py`: table-driven tests for each function — window check (in/out of range), fee calc (both conditions), fraud score (0 flags / 1 flag / all 3 flags stacking), refund processing returns expected shape.
- **Verification:** `pytest tests/test_services.py -v` all green; fraud score test asserts exact expected float sums per Decisions weights. ✅ (42 passed; full suite 67 passed — venv `.venv` Python 3.11.9)

### Phase 3 — LangGraph Core (no LLM, no interrupts yet)
*Depends on Phases 1-2 (parallel-safe with Phase 4 once this lands). Build graph skeleton with deterministic stand-in for the classify node first, so structure/loops are tested before adding LLM/interrupt complexity.*
- [x] `app/graph.py` — define nodes as plain functions operating on `ReturnState`:
  - `validate_policy_node`: looks up order via `services.get_order`, checks window; sets `status=denied_policy` and short-circuits if invalid.
  - `classify_condition_node`: **stub version** — simple keyword match on `reason_text` (e.g. contains "broken"/"defect" → damaged_defective, else buyer_remorse) — replaced with real LLM call in Phase 5.
  - `check_photo_proof_node`: if `item_condition == damaged_defective` and not `photo_provided` and `photo_retry_count < MAX_PHOTO_RETRIES` → returns state requesting photo (status=`awaiting_photo`); a conditional edge routes back to itself when resumed with new photo info, else proceeds.
  - `calculate_fee_node`: sets `shipping_fee` via `services.calculate_shipping_fee`.
  - `fraud_check_node`: sets `fraud_score`/`fraud_flags` via `services.compute_fraud_score`; computes `refund_amount = item_value - shipping_fee`.
  - `finalize_refund_node`: calls `services.process_refund`, sets `status=completed`.
  - `reject_policy_node`: terminal node for policy denial.
  - Conditional edge function `route_after_fraud_check`: high-value/fraud → placeholder `human_gate` node (Phase 4 will make it interrupt); else → `finalize_refund_node`.
  - Wire graph with `StateGraph(ReturnState)`, `add_node`, `add_edge`/`add_conditional_edges`, compile with **no checkpointer** for this phase (use default in-memory, `graph.invoke(...)`).
- [x] `tests/test_graph.py` (part 1): invoke full graph synchronously with a happy-path damaged-item-with-photo input → assert final `status == completed` and correct `refund_amount`/`shipping_fee`. Invoke with an order >30 days old → assert `status == denied_policy`. Invoke with buyer's remorse condition → assert `shipping_fee == 5.99`.
- **Verification:** `pytest tests/test_graph.py -v` (happy paths only, no interrupts yet). ✅ (19 passed — includes routing tests: high-value → `awaiting_approval` at placeholder `human_gate`, CUST-A velocity → fraud 0.4 → gate, damaged-no-photo → `awaiting_photo` pause; full suite 86 passed. Note: LangGraph 1.2.11 `invoke` returns only keys updated by nodes — unset defaults absent from result dict; buyer's-remorse fee applies before the human gate, so ORD-1001 refund is $893.01.)

### Phase 4 — Interrupts, Cyclical Loop & SQLite Checkpointer
*Depends on Phase 3. This is the core HITL/persistence requirement from Instructions.md.*
- [x] Replace placeholder photo-loop and `human_gate` with real LangGraph `interrupt()` calls:
  - `check_photo_proof_node` calls `interrupt({"reason": "photo_required", "order_id": ...})` when photo missing; on resume, the resumed value updates `photo_provided`/`photo_url`/increments `photo_retry_count`, then conditional edge loops back to `check_photo_proof_node` again (bounded by `MAX_PHOTO_RETRIES`) or proceeds to `calculate_fee_node`.
  - `human_gate_node` calls `interrupt({"reason": "manager_approval_required", "refund_amount": ..., "fraud_flags": ...})`; on resume with `{"decision": "approve"|"reject", "manager_note": ...}` routes to `finalize_refund_node` or a new `reject_by_manager_node`.
- [x] Compile graph with `SqliteSaver.from_conn_string(settings.SQLITE_DB_PATH)` as checkpointer; require `thread_id` in `config={"configurable": {"thread_id": ...}}` for every invoke. (Impl: long-lived `sqlite3.connect(path, check_same_thread=False)` + `SqliteSaver(conn, serde=...)` — `from_conn_string` is a one-shot context manager unsuitable for a persistent FastAPI app.)
- [x] Add `app/graph.py` helper `run_graph(thread_id, initial_state)` and `resume_graph(thread_id, resume_value: Command)` used later by the API layer. (Plus `get_state_snapshot(thread_id)` and `thread_config()`.)
- [x] `tests/test_graph.py` (part 2 — interrupts):
  - Test photo loop: invoke with damaged item + `photo_provided=False` → assert graph pauses (`interrupt` surfaced, state `status=awaiting_photo`); resume with photo → assert graph proceeds; test exceeding `MAX_PHOTO_RETRIES` → assert graceful terminal state (e.g. `status=denied_policy` or auto-reject) instead of infinite loop. (Implemented per plan "Further Considerations 2": exhaustion proceeds to fraud check → `no_photo_proof` flag (0.4) → human gate `awaiting_approval`, not auto-deny.)
  - Test high-value gate: invoke with `item_value` producing `refund_amount > 200` → assert graph pauses at `human_gate_node`; resume with `decision=approve` → assert `status=completed`; resume with `decision=reject` → assert `status=rejected`.
  - Test persistence: after pausing, create a **new** graph instance pointed at the same sqlite file/thread_id, resume from there → assert it picks up correctly (proves durable checkpointing, not just in-memory).
- **Verification:** `pytest tests/test_graph.py -v` all interrupt/loop/persistence tests green; inspect `checkpoints.sqlite` file is created and non-empty after a run. ✅ (103 passed full suite; graph tests 36: photo loop pause/resume/loop-back/retry-exhaustion→fraud-flag→gate, approve→completed, reject→rejected, unrecognized-decision fail-closed, cross-instance SQLite persistence both gates, checkpoint file 102400 bytes. Key design: gate nodes use two-pass pattern — first pass sets `awaiting_photo`/`awaiting_approval` and loops back to itself via conditional edge, second pass calls `interrupt()` — so the checkpointed state exposes the pause status to the API layer. Serde: explicit `JsonPlusSerializer(allowed_msgpack_modules=...)` allowlist for `app.schemas` enums silences LangGraph 1.2.11's unregistered-type deserialization warning.)

### Phase 5 — Ollama Cloud LLM Classification Node
*Depends on Phase 3 (replaces the stub `classify_condition_node`). Can run in parallel with Phase 4.*
- [x] Add `app/llm.py`: builds `ChatOllama` client using `langchain_ollama.ChatOllama(model=settings.OLLAMA_MODEL, base_url=settings.OLLAMA_BASE_URL, headers={"Authorization": f"Bearer {settings.OLLAMA_API_KEY}"})` (confirm exact auth kwarg against installed `langchain-ollama` version's docs/signature before finalizing — flagged as a verify-at-implementation-time detail). ✅ (Verified against langchain-ollama 1.1.0: there is NO dedicated `headers` field — auth goes via `client_kwargs={"headers": {"Authorization": "Bearer ..."}}`; live PONG test passed against `https://ollama.com` with the real key.)
- [x] Define a small structured-output prompt/parser: input `reason_text` → output constrained to `damaged_defective` | `buyer_remorse` (use `.with_structured_output(...)` or a strict enum-parsing prompt with fallback keyword heuristic from Phase 3 if the LLM response doesn't parse cleanly). ✅ (`.with_structured_output()` FAILS with this model/endpoint — model emits the bare enum string and langchain's JSON parser raises `OutputParserException: Invalid json output: damaged_defective`. Working mechanism, verified live: `ChatOllama(format=<json-schema>)` with a single-enum-property schema makes `gpt-oss:120b` return the bare enum string directly; tolerant `parse_condition` also accepts `{"condition": "..."}` / quoted / padded forms.)
- [x] Update `classify_condition_node` in `graph.py` to call `app/llm.py`'s classifier instead of the keyword stub; keep the keyword stub function in `services.py` or `llm.py` as an explicit fallback (`_fallback_classify`) for parse failures — do not fail the whole run. ✅ (Stub stays in `graph.py`; `llm._fallback_classify` imports it. Fallback also triggers on missing `OLLAMA_API_KEY` and any LLM exception. Decision log now says "(LLM classifier)".)
- [x] `tests/test_llm.py`: unit test the parser/fallback logic with mocked LLM responses (valid enum string, garbage string, empty string) — assert correct enum mapping and fallback trigger. Mark a separate test `@pytest.mark.integration` that hits the real Ollama Cloud endpoint (skipped by default unless `OLLAMA_API_KEY` env var present) to sanity-check live connectivity. ✅ (23 unit tests + 2 live integration tests; `pytest.ini` deselects integration by default via `addopts = -m "not integration"`, run manually with `pytest -m integration`.)
- **Verification:** `pytest tests/test_llm.py -v` (unit tests always run); `pytest tests/test_llm.py -m integration` manually with real `.env` key to confirm live call. ✅ (23 unit passed; 2 integration passed live — damaged & remorse both classified correctly through Ollama Cloud in ~4s. Also added: `tests/test_graph.py` autouse fixture stubs `llm.classify_reason` so graph tests stay deterministic/fast (full suite 126 passed in ~3s vs 50s when graph tests hit the live LLM). Note: available cloud models differ from .env default — `gpt-oss:120b` IS available (verified via `client.list()`); the earlier 404 was from the ollama module-level `chat()` bypassing the configured client and hitting localhost.)

### Phase 6 — FastAPI Layer
*Depends on Phases 4 and 5 (needs the finished graph with interrupts + real classifier).*
- [x] `app/main.py`:
  - `POST /returns` — body `ReturnRequest`; generates a new `thread_id` (uuid4); calls `run_graph`; returns `ReturnResponse` reflecting current status (`awaiting_photo`, `awaiting_approval`, `completed`, or `denied_policy`).
  - `POST /returns/{thread_id}/photo` — body `PhotoResubmitRequest`; resumes the photo-loop interrupt via `Command(resume=...)`; returns updated `ReturnResponse`.
  - `POST /returns/{thread_id}/approve` — body `ApprovalRequest`; resumes human-gate interrupt with `decision=approve`.
  - `POST /returns/{thread_id}/reject` — body `ApprovalRequest`; resumes human-gate interrupt with `decision=reject`.
  - `GET /returns/{thread_id}` — reads current checkpointed state via the graph's `get_state(config)`, returns `ReturnResponse`.
  - 404 handling for unknown `thread_id`; 409/400 handling if resuming a thread that isn't actually paused. ✅ (404 via empty `snapshot.values` on never-checkpointed threads; 409 via `snapshot.next` — covers both finished runs and paused-at-wrong-gate (photo posted to a manager-gate thread, etc.). Fee/fraud/refund fields are only surfaced in `ReturnResponse` once the workflow passes the fraud check (`awaiting_approval` and beyond); before that they'd be misleading 0.0 defaults. `_response_from_state` normalizes raw checkpoint values through `ReturnState.model_validate` since LangGraph omits channels no node has written.)
- [x] `tests/test_api.py` using `fastapi.testclient.TestClient`:
  - Full happy path: `POST /returns` (buyer's remorse, low value) → immediately `completed`.
  - Photo loop path: `POST /returns` (damaged, no photo) → `awaiting_photo` → `POST /returns/{id}/photo` → `completed`.
  - High-value approval path: `POST /returns` (value > $200) → `awaiting_approval` → `POST /returns/{id}/approve` → `completed`; separately test `/reject` → `rejected`.
  - Policy-denial path: order >30 days old → `denied_policy` immediately.
  - Error cases: unknown `thread_id` on `GET`/`approve` → 404; approving a thread not awaiting approval → 409.
  (16 tests in 6 classes; `client` fixture monkeypatches `SQLITE_DB_PATH` to a tmp file and resets the cached `_default_graph` per test so each gets a fresh checkpoint store; autouse LLM stub keeps tests deterministic. Extra coverage: empty photo resubmission re-pauses, photo-on-manager-gate and approve-on-photo-paused 409s, 422 invalid body, restart-equivalence test that rebuilds the graph on the same sqlite file mid-pause.)
- **Verification:** `pytest tests/test_api.py -v` all green; manual smoke test via `uvicorn app.main:app --reload` + `curl`/httpie against each route. ✅ (16 passed; full suite 142 passed, 2 integration deselected. Live uvicorn smoke: remorse POST → `completed` refund 123.51; damaged-no-photo → `awaiting_photo` → `/photo` → `completed` fee 0.00 refund 129.50; high-value → `awaiting_approval` refund 893.01 fraud 0.7 [velocity+high_refund] → `/approve` → `completed`; unknown GET → 404. Restart persistence: killed server mid-interrupt, restarted on same `checkpoints.sqlite`, `GET` returned `awaiting_approval`, `/approve` resumed → `completed` refund 899.00.)

### Phase 7 — Polish & Docs
*Depends on all prior phases passing.*
- [x] Finalize `README.md`: setup (venv, `pip install -r requirements.txt`, copy `.env.example` → `.env`), run server command, example `curl` calls for each endpoint/flow (happy path, photo loop, approval loop), how to run tests (`pytest -v`, `pytest -m "not integration"`). ✅ (Full rewrite: architecture diagram of node flow, business-rule tables, setup/run instructions, curl examples for all 4 flows + inspect, error semantics, endpoint summary, test commands, mock-data reference table.)
- [x] Full regression pass: `pytest -v` (excluding live-LLM integration test) — all green. ✅ (142 passed, 2 integration deselected, ~4s — venv `.venv` at repo root, run from `return-agent/` cwd.)
- [x] Manual end-to-end smoke test via running server + hitting all 3 flows (buyer's remorse auto-complete, damaged+no-photo loop, high-value manager approval) with `curl`, confirming `checkpoints.sqlite` persists across a server restart mid-interrupt. ✅ (Live uvicorn on port 8765 [port 8000 was occupied by an unrelated app]: flow 1 remorse → completed refund 123.51 fee 5.99; flow 2 damaged-no-photo → awaiting_photo → /photo → completed refund 129.50 fee 0.00; flow 3 high-value → awaiting_approval refund 899.00 fraud 0.7 [high_return_velocity, high_refund_amount] → /approve → completed; also verified /reject → rejected and stale-order → denied_policy; unknown thread → 404. Persistence: paused a high-value run at awaiting_approval, killed the server, restarted on the same checkpoints.sqlite, GET returned awaiting_approval with full computed fields, /approve resumed → completed.)
- **Verification:** Full test suite green; manual smoke test confirms persistence survives a server restart (kill `uvicorn`, restart, `GET /returns/{thread_id}` still returns the paused state, resume succeeds). ✅ ALL PHASES COMPLETE — project delivered per Instructions.md.

## Relevant files (all new, per Instructions.md §3)
- `return-agent/app/config.py` — env settings singleton.
- `return-agent/app/schemas.py` — `ReturnState`, enums, API request/response models.
- `return-agent/app/services.py` — mock order DB, fee calc, fraud heuristics, mock payment gateway.
- `return-agent/app/llm.py` — Ollama Cloud `ChatOllama` wrapper + classification parser/fallback.
- `return-agent/app/graph.py` — `StateGraph` nodes/edges, `interrupt()` gates, `SqliteSaver`, `run_graph`/`resume_graph` helpers.
- `return-agent/app/main.py` — FastAPI routes.
- `return-agent/tests/test_schemas.py`, `test_services.py`, `test_graph.py`, `test_llm.py`, `test_api.py`.
- `return-agent/requirements.txt`, `.env.example`, `README.md`.

## Further Considerations
1. **`langchain-ollama` cloud auth signature** — the exact kwarg for passing `OLLAMA_API_KEY` as a Bearer token to `ChatOllama` should be verified against the installed package version's docs at implementation time (API surface may differ from local-Ollama usage); fallback plan is the OpenAI-compatible proxy pattern from a prior project (documented in user's persistent memory) if direct cloud auth doesn't work cleanly.
2. **Photo-retry exhaustion behavior** — plan defaults to auto-denying (`status=denied_policy`) after `MAX_PHOTO_RETRIES` (3) failed attempts; confirm this is acceptable vs. e.g. auto-escalating to manager review instead.
