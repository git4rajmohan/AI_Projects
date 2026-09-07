# How to Test — Return & Fraud Prevention Agent

Complete test guide: unit suite, API (curl), UI (Streamlit) click-by-click, persistence, and live-LLM integration tests.

---

## 1. Mock data cheat sheet

Source: `return-agent/app/services.py` (order dates are relative to server start, so windows stay valid).

| Order | Customer | Value | Age | Use for |
|---|---|---|---|---|
| ORD-1001 | CUST-A | $899.00 | 5d | High-value gate + velocity fraud |
| ORD-1002 | CUST-B | $129.50 | 10d | Low-value auto-complete / photo loop |
| ORD-1003 | CUST-C | $79.99 | 45d | Policy denial (stale) |
| ORD-1004 | CUST-A | $349.00 | 25d | High-value gate (fresh) |
| ORD-1005 | CUST-D | $45.00 | 60d | Policy denial (stale, low) |
| ORD-1006 | CUST-D | $15.00 | 2d | Cheapest auto-complete |

**Fraud weights:** velocity (≥3 returns/30d, only CUST-A) +0.4 · no-photo-after-retries +0.4 · refund >$500 +0.3.

**Human gate triggers when:** refund >$200 **or** fraud score ≥0.7 **or** `no_photo_proof` flag present.

**Fee rules:** damaged/defective = $0.00 · buyer's remorse = $5.99.

---

## 2. Prerequisites

1. Backend running on port **8765** (port 8000 is occupied by an unrelated app on this machine):
   `uvicorn app.main:app --port 8765`
2. Streamlit UI running on port **8501**:
   `streamlit run streamlit_app.py` (launch detached: `Start-Process -WindowStyle Hidden`)
3. Baseline unit suite:
   ```
   cd return-agent
   ..\.venv\Scripts\python.exe -m pytest -v
   ```

---

## 3. API scenarios (curl against http://localhost:8765)

| # | Scenario | Request | Expected |
|---|---|---|---|
| S1 | Remorse auto-complete | `POST /returns` ORD-1002, reason "changed my mind, don't like the color", photo false | `completed`, fee 5.99, refund 123.51, no gate |
| S2 | Damaged with photo | `POST /returns` ORD-1002, reason "screen cracked on arrival", photo true | `completed`, fee 0.00, refund 129.50 |
| S3 | Cheapest auto-complete | S1 with ORD-1006 | `completed`, refund 9.01 |
| S4 | Photo loop pause/resume | damaged ORD-1002, no photo → then `POST /returns/{tid}/photo` photo true | `awaiting_photo` → `completed` |
| S5 | Empty photo resubmit re-pauses | during S4's pause, `/photo` with photo false | still `awaiting_photo`, retry +1 |
| S6 | Retry exhaustion → gate | 3× empty `/photo` submissions | `no_photo_proof` flag (+0.4) → `awaiting_approval`; approve → `completed` |
| S7 | High-value approve | ORD-1001, reason "not happy with it" | `awaiting_approval`, refund 893.01, fraud 0.7 (velocity+high_refund) → `/approve` → `completed` |
| S8 | High-value reject | ORD-1004 → `/reject` with note | `awaiting_approval` → `rejected` |
| S9 | Policy denial | ORD-1003 (also ORD-1005) | `denied_policy` immediately |
| S10 | Unknown thread | `GET /returns/nonexistent` | 404 |
| S11 | Wrong-gate resume | approve a completed thread; approve a photo-paused thread; photo a manager-paused thread | 409 each |
| S12 | Invalid body | `POST /returns` missing `order_id` | 422 |
| S13 | Audit trail | `GET /returns/{tid}` on completed run | `decision_log` has full node trail (5+ entries on remorse path) |

Example curls:

```
# S1
curl -X POST http://localhost:8765/returns -H "Content-Type: application/json" ^
  -d "{\"order_id\":\"ORD-1002\",\"item_id\":\"SKU-HEADPHN-02\",\"reason_text\":\"changed my mind\",\"photo_provided\":false}"

# S4 resume
curl -X POST http://localhost:8765/returns/{thread_id}/photo ^
  -d "{\"photo_provided\":true,\"photo_url\":\"https://pics.example/x.jpg\"}"

# S7 approve
curl -X POST http://localhost:8765/returns/{thread_id}/approve ^
  -d "{\"manager_note\":\"ok\"}"
```

---

## 4. UI control cheat sheet (Streamlit, http://localhost:8501)

| Control | Where | How to interact |
|---|---|---|
| View switch | Sidebar radio (`Customer / Manager / Pipeline`) | Click the **word** (e.g. "Manager"), not the radio dot |
| Order picker | Customer view, left column | Click the "Pick the order to return…" box → click the option row, e.g. `ORD-1002 — Wireless Headphones ($129.50, ordered …)` |
| Reason | `Reason for return` text area | Click, type |
| Photo checkbox | `I can provide a photo` | Click the checkbox/label; a `Photo URL` input appears only when checked |
| Submit return | Blue primary button under the form | Click |
| Track panel | Right column | `Thread ID` auto-fills after a submission; click **Look up** (or 🔄 Refresh status) |
| Photo resubmit | Right column, only when status is 🟡 `awaiting_photo` | Optional checkbox `I have a photo this time` → **Submit photo** |
| Manager queue | Manager view, left | Click the expander header → type in `Manager note` → click **✅ Approve** / **❌ Reject** |
| All returns | Manager view, right | `Filter by status` selectbox + 🔄 Refresh list |
| Pipeline | Pipeline view | 🔄 Refresh → expand a return card to see the 7-stage stepper + audit trail |

**Setup:** sidebar `API base URL` = `http://127.0.0.1:8765`. Click every 🔄 refresh button before asserting — lists are cached in session state.

---

## 5. UI scenarios — inputs & expected results

| # | Order | Reason text (type exactly) | Photo checkbox | Expected outcome |
|---|---|---|---|---|
| A | ORD-1002 | `Changed my mind, don't like the color` | unchecked | ✅ `completed`, fee $5.99, refund $123.51, fraud 0.0 |
| B | ORD-1002 | `Headphones arrived cracked` | checked + `https://pics.example/hp.jpg` | ✅ `completed`, fee $0.00, refund $129.50 |
| C | ORD-1002 | `Headphones arrived cracked` | unchecked → resume with photo | 🟡 `awaiting_photo` → ✅ `completed` $129.50 |
| D | ORD-1002 | `Headphones arrived cracked` | 3× unchecked resubmits | 🟠 `awaiting_approval`, fraud 0.4, flag `no_photo_proof` |
| E | ORD-1001 | `Not happy with it` | unchecked | 🟠 `awaiting_approval`, refund $893.01, fraud 0.7 → approve → ✅ |
| F | ORD-1004 | `Not happy with it` | unchecked | 🟠 `awaiting_approval`, refund $343.01, fraud 0.4 → reject → 🔴 `rejected` |
| G | ORD-1003 | `Just want to return it` | any | ⛔ `denied_policy` immediately (outside 30-day window) |
| H | ORD-1006 | `Don't want it anymore` | unchecked | ✅ `completed`, fee $5.99, refund $9.01 |

### A — Remorse auto-complete
1. Sidebar: click **Customer**.
2. Click the order box → select `ORD-1002 — Wireless Headphones ($129.50, ordered …)`.
3. Click `Reason for return`, type the A text.
4. Leave `I can provide a photo` **unchecked**.
5. Click **Submit return**.
6. Assert: **Thread ID** appears, chip ✅ `completed`, message mentions refund processed; metrics row: Refund `$123.51`, Shipping fee `$5.99`, Fraud score `0.0`, Next action `none`.

### B — Damaged with photo upfront
1. Same as A but select ORD-1002 again, type the B text.
2. Click the `I can provide a photo` checkbox → a `Photo URL` field appears → type `https://pics.example/hp.jpg`.
3. Click **Submit return** → expect ✅ `completed`, fee `$0.00`, refund `$129.50`.

### C — Photo loop pause → resume
1. Submit: ORD-1002, B text, photo checkbox **unchecked** → expect 🟡 `awaiting_photo`, message asks for photo proof, Refund metric shows `—` (fields hidden before the fraud check).
2. The right column's `Thread ID` is pre-filled → click **Look up** (or 🔄 Refresh status).
3. In the tracked panel: info banner "📷 This return needs photo proof…" appears → click the `I have a photo this time` checkbox → type any URL → click **Submit photo**.
4. Expect chip flips to ✅ `completed`, fee `$0.00`, refund `$129.50`.

### D — Empty resubmission re-pause + retry exhaustion → manager gate
1. Submit like C (damaged, no photo) → 🟡 `awaiting_photo`.
2. Click **Look up**, leave `I have a photo this time` **unchecked**, click **Submit photo** → still 🟡 `awaiting_photo` (retry count +1). Repeat **2 more times** (3 empty submits total).
3. After the 3rd, expect 🟠 `awaiting_approval`, fraud `0.4`, warning chip "Fraud flags: `no_photo_proof`", refund `$129.50`.
4. Sidebar → click **Manager** → click **🔄 Refresh queue** → an expander `🟠 awaiting_approval · ORD-1002 · refund $129.50 · …` exists → click to expand.
5. Type a note (e.g. `No proof, but low value — honor it`) → click **✅ Approve**.
6. Expect green banner "✅ Approved … → **completed** (refund $129.50)" and the queue refreshes to "No returns awaiting approval 🎉".

### E — High-value approve
1. Customer view → select `ORD-1001 — Ultrabook 14" ($899.00, ordered …)` → type E text → unchecked photo → **Submit return**.
2. Expect 🟠 `awaiting_approval`, Refund `$893.01`, fee `$5.99`, fraud `0.7`, flags `high_return_velocity`, `high_refund_amount`.
3. Manager view → 🔄 Refresh queue → expand the ORD-1001 expander → note `High value, legitimate customer` → **✅ Approve** → banner shows **completed**.
4. Pipeline check (scenario I): Manager ✅, Refund ✅.

### F — High-value reject
1. Customer view → `ORD-1004 — 27" 4K Monitor ($349.00, ordered …)` → type F text → unchecked → **Submit return** → 🟠 `awaiting_approval`, refund `$343.01`, fraud `0.4`, flag `high_return_velocity` only.
2. Manager view → refresh queue → expand ORD-1004 → note `Suspicious pattern` → click **❌ Reject**.
3. Expect banner "❌ Rejected … → **rejected**"; in Pipeline view: Manager ❌, Refund ⏭️; in the return details an info line "Manager note: Suspicious pattern".

### G — Policy denial
1. Customer view → select `ORD-1003 — Mechanical Keyboard ($79.99, ordered …)` → type G text → **Submit return**.
2. Expect ⛔ `denied_policy` immediately, message about the 30-day window, Refund/Fee/Fraud metrics show `—`. Repeat with `ORD-1005 — Ergonomic Mouse` for a second denial.

### H — Unknown thread 404
1. Customer view, right column: clear `Thread ID`, type `does-not-exist` → click **Look up**.
2. Expect a red error banner `API /returns/does-not-exist → HTTP 404: …`. The 409 wrong-gate case can't be triggered in the UI by design (approve buttons only render on `awaiting_approval` items) — that's covered by the curl tests (S11).

### I — Pipeline view verification
1. Sidebar → click **Pipeline** → click **🔄 Refresh**.
2. Top metrics row should reflect everything run so far (e.g. Awaiting photo 0, Awaiting approval 0, Completed ≥5, Rejected 1, Denied 2).
3. Expand each card and check the stepper:
   - A/H: `Policy ✅ Classify ✅ Photo ⏭️ Fee ✅ Fraud ✅ Manager ⏭️ Refund ✅`
   - B/C/D: same but `Photo ✅` and D's `Manager ✅`
   - F: `… Manager ❌ Refund ⏭️`
   - G: `Policy ❌` + all rest `⏭️`
4. For a 🟡 `awaiting_photo` card (make one fresh via scenario C without resuming): the Photo stage shows 🔵 with banner "Now: **Photo** — waiting for the customer…"; after one empty resubmit the banner gains `(attempt 1/3)`.
5. For a 🟠 card: banner says "Now: **Manager** — waiting for a manager decision… resolve it in the **Manager** view".
6. Audit trail: the remorse happy path shows a 5-entry numbered log (validate → classified as buyer_remorse (LLM classifier) → shipping fee → fraud score → refund processed); expand any card and eyeball that entries match the stages shown.

### J — All-returns filter
1. Manager view, right column: `Filter by status` → select `awaiting_approval` → the table should list only paused-at-manager threads (create one via E without approving if needed). Switch to `(all)` → everything appears.

> Order of execution matters only for D (do it before E/F so the manager queue is easy to read); A/B/G can run anytime.

---

## 6. Persistence (restart survival)

1. Start scenario E but stop at `awaiting_approval` (don't approve).
2. Kill the uvicorn process on 8765.
3. Restart the backend on the same `checkpoints.sqlite`.
4. `GET /returns/{thread_id}` → still `awaiting_approval` with fee/fraud/refund intact.
5. `POST /approve` → `completed`. Same check with a photo-gate pause instead.

## 7. Live LLM (integration tests)

```
cd return-agent
..\.venv\Scripts\python.exe -m pytest -m integration -v
```
Verifies real Ollama Cloud classification for both a damaged text and a remorse text (~4s each). Requires `OLLAMA_API_KEY` in `.env`.

---

## 8. GOTCHAs

- Backend must run on **8765** (8000 is taken by an unrelated app returning /api/* routes).
- After editing app code, restart **both** uvicorn (8765) and streamlit (8501) — stale processes serve stale `decision_log` (pipeline stages all show ⚪).
- Streamlit launch from a background terminal dies when the terminal exits → launch detached (`Start-Process -WindowStyle Hidden`).
- All list views (Manager queue, All returns, Pipeline) cache in session state → click the 🔄 refresh buttons after any state-changing action, or open a fresh browser tab.