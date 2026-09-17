## Plan: Streamlit UI for the Return & Fraud Prevention Agent

Add a Streamlit app that drives the existing FastAPI backend (`return-agent/app/main.py`) end-to-end:
a customer view to start/track returns (incl. the photo-resubmit loop) and a manager view showing a
live pending-approvals queue with approve/reject actions. The backend is feature-complete (142 tests
green) but has no "list all returns" or "list mock orders" capability, so a small additive backend
step (Phase A) precedes the UI build (Phase B). No auth, no image upload, no auto-polling — manual
refresh buttons, matching the project's existing simplicity.

## Decisions (confirmed with user)
- UI tech: **Streamlit** (pure Python, fastest to demo an agent workflow).
- Scope: **both** customer flow (start/track/photo-resubmit) and manager console (approval queue).
- Order picker: dropdown of the 6 mock orders (`ORD-1001`..`ORD-1006`), populated from a new `GET /orders` endpoint — not hardcoded/duplicated in the UI.
- No new "list returns" storage layer — reuse the existing `SqliteSaver` checkpointer's thread enumeration instead of adding an index table/file.
- `ReturnResponse` gains `order_id`/`item_id`/`reason_text` (always populated, not gated behind computed-status) so the manager queue can identify what it's approving without a second lookup.
- No photo file upload — keep the existing `photo_provided: bool` + `photo_url: str` (free-text) contract.
- No auth on the manager view (mirrors the backend, which has none either) — explicitly out of scope.

## Steps

### Phase A — Backend: UI-support endpoints (small, additive)
*No dependency; must land before Phase B since the UI calls these routes.*
1. [app/schemas.py](return-agent/app/schemas.py) — add `order_id: Optional[str]`, `item_id: Optional[str]`, `reason_text: Optional[str]` to `ReturnResponse`; add new `OrderSummary` model (`order_id`, `item_id`, `item_name`, `item_value`, `order_date`).
2. [app/graph.py](return-agent/app/graph.py) — add `list_thread_ids() -> list[str]`: dedupe `get_default_graph().checkpointer.list(None)` by `config["configurable"]["thread_id"]`, keeping only the first (most recent) checkpoint tuple per thread. **Verify at implementation time** whether `SqliteSaver.list(None)` yields newest-first per thread (LangGraph docs/source) — if not, sort by `checkpoint["ts"]` descending before deduping.
3. [app/main.py](return-agent/app/main.py):
   - Update `_response_from_state` to always set `order_id`, `item_id`, `reason_text` from `state` (not gated behind `_COMPUTED_STATUSES`).
   - New `GET /orders` → `List[OrderSummary]` built from `services.MOCK_ORDERS.values()`.
   - New `GET /returns` with optional `status: Optional[ReturnStatus]` query param → for each id from `graph.list_thread_ids()`, load its snapshot and build a `ReturnResponse` via the existing `_response_from_state`; filter by `status` if provided; skip/exclude threads with empty `values` (defensive).
4. [tests/test_api.py](return-agent/tests/test_api.py) — add cases: `GET /orders` returns the 6 seeded mock orders; `GET /returns` is empty before any run, includes newly created threads after, filters correctly by `?status=awaiting_approval`; existing response assertions extended to check `order_id`/`item_id`/`reason_text` are present.
5. **Verification:** `pytest tests/test_api.py -v` (and full suite) green; manual `curl http://127.0.0.1:8000/orders` and `/returns` against a running server confirm shapes.

### Phase B — Streamlit UI
*Depends on Phase A (`/orders`, `/returns` must exist). Reuses existing `/returns`, `/returns/{id}/photo`, `/approve`, `/reject`, `/returns/{id}` routes as-is.*
1. [requirements.txt](return-agent/requirements.txt) — add `streamlit` (reuse the already-present `httpx` for API calls, no new HTTP client dependency).
2. New [return-agent/streamlit_app.py](return-agent/streamlit_app.py):
   - Sidebar: editable "API base URL" text input (default `http://127.0.0.1:8000`, overridable — repo notes port 8000 can be occupied locally, recommend `8765` in README), and a view radio: **Customer** / **Manager**.
   - Small `api_get(path)` / `api_post(path, json)` helpers wrapping `httpx.Client` calls with try/except → `st.error(...)` on non-2xx/connection failure, returning `None` so callers can guard.
   - **Customer view**:
     - "Start a new return": selectbox populated from `GET /orders` (cached via `st.cache_data(ttl=30)`), label like `ORD-1001 — Ultrabook 14" ($899.00, ordered 2026-08-31)`; auto-fills `order_id`/`item_id`, shows `item_value`/`order_date` as captions; `reason_text` (`st.text_area`), `photo_provided` (`st.checkbox`), `photo_url` (`st.text_input`, shown when checked); submit → `POST /returns`; store `thread_id` in `st.session_state`; render status/message/next_action plus computed fields (refund/fee/fraud) when present.
     - "Track / continue a return": `thread_id` input (pre-filled from session state), "Refresh status" → `GET /returns/{id}`; when status is `awaiting_photo`, show inline resubmit mini-form → `POST /returns/{id}/photo`, then re-render.
   - **Manager view**:
     - "Pending approvals" (default filter `awaiting_approval` via `GET /returns?status=awaiting_approval`): one `st.expander` per thread showing order/item/reason/refund_amount/fraud_score/fraud_flags, with `manager_note` text input + **Approve**/**Reject** buttons calling the existing endpoints, then refresh the list.
     - Optional "All returns" table below with a status-filter selectbox (`GET /returns?status=...` or unfiltered) for demo visibility.
3. [README.md](return-agent/README.md) — add a "Running the UI" section: install deps, start backend (`uvicorn app.main:app --reload --port 8765`), start UI in a second terminal (`streamlit run streamlit_app.py`), note the port-8000 conflict, and a short walkthrough of all 3 demo flows via the UI.
4. **Verification (manual, no new automated UI tests):** with backend + Streamlit both running, exercise: (a) buyer's-remorse low-value order → immediate `completed`; (b) damaged item, no photo (e.g. reason "screen arrived cracked") → `awaiting_photo` → resubmit photo in UI → `completed`; (c) high-value order (ORD-1001, $899) → `awaiting_approval` → appears in Manager queue → Approve → `completed` (separately test Reject → `rejected`); (d) stale order (ORD-1003/ORD-1005) → `denied_policy` shown immediately; (e) unknown `thread_id` in Track section → error surfaced, not a crash.

## Relevant files
- `return-agent/app/schemas.py` — `ReturnResponse` additive fields, new `OrderSummary`.
- `return-agent/app/graph.py` — new `list_thread_ids()` helper.
- `return-agent/app/main.py` — `_response_from_state` update, new `GET /orders`, new `GET /returns`.
- `return-agent/tests/test_api.py` — new endpoint coverage.
- `return-agent/requirements.txt` — add `streamlit`.
- `return-agent/streamlit_app.py` — new, the UI itself.
- `return-agent/README.md` — new "Running the UI" section.

## Phase C — Pipeline fleet board (done 2026-09-05)
Third sidebar view rendering every return across the agent's 7-stage state machine
(Policy → Classify → Photo → Fee → Fraud → Manager → Refund) as an expander card with a
per-stage stepper: ✅ done · 🔵 active · ⚪ pending · ⏭️ skipped · ❌ failed, derived purely
from `status` + `decision_log` (no graph re-runs). Sections: Active (photo/manager gates,
expanded by default, with "Now: …" banner + retry attempt), Completed, Rejected/Denied;
5 count metrics on top. Backend enabler: `ReturnResponse.decision_log` always populated in
`_response_from_state` (+ API test asserting the 5-entry audit trail for a happy path).

## Verification (overall)
1. `pytest -v` (from `return-agent/`, using the repo-root `.venv`) — full suite green, including new `/orders` and `/returns` cases.
2. Manual end-to-end UI smoke test per Phase B step 4 (all 5 scenarios).
3. Confirm `checkpoints.sqlite` persistence still works: restart the FastAPI server mid-`awaiting_approval` pause created via the UI, refresh the Manager queue — the thread should still appear and resolve correctly.

## Further Considerations
1. **Checkpointer thread-listing order** — `SqliteSaver.list(None)` ordering (newest-first vs oldest-first per thread) isn't yet confirmed against the installed `langgraph-checkpoint-sqlite` version; Phase A step 2 explicitly calls out verifying this and sorting by timestamp if needed, to avoid the `/returns` list showing stale state for a thread with multiple checkpoints.
2. **Auto-refresh vs manual buttons** — recommended: manual "Refresh" buttons only (simplest, matches backend's synchronous request/response style). Alternative: add a `st.rerun()` timer loop for the Manager queue for a more "live" feel — deliberately deferred as an enhancement, not required for this plan.
