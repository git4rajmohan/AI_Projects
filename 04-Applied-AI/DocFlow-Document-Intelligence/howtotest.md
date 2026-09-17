# How to Test — All 10 Invoice Patterns

Step-by-step test matrix for the DocFlow reviewer. Every upload exercises one
pattern from `demo_script.md`; the UI shows the workflow strips (🤖 agent steps,
🧍 human steps: green = done, yellow = active, grey = not reached).

## Setup (once)

```powershell
# 1. stop the API (Ctrl+C in its terminal), then reset the DB:
del data\docflow.db
.venv\Scripts\python.exe -c "import app.db; app.db.seed('data/docflow.db')"

# 2. restart the API
.venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000

# 3. (separate terminal) start the UI
.venv\Scripts\python.exe -m streamlit run ui/reviewer.py
```

In the UI sidebar: type **`yuki`** in *Reviewer name* (unlocks the action
buttons). API base stays `http://127.0.0.1:8000`.

## Test matrix

Upload each file via the UI upload box (files in `data/invoices/`), check the
banner + workflow strips, act where marked.

| # | Upload | Expected (banner + strips) | Act as `yuki` |
|---|--------|----------------------------|----------------|
| 1 | `d1_normal.pdf` | All 🤖 green → `in_review` 🧍 yellow (¥850k = manager band) | **Approve** → loop strip all green ✓ |
| 2 | `d2_qty_mismatch.pdf` | EXCEPTION — per-line table: Product A qty 150 vs PO 100 🚨 | **Reject** (mismatch is real) |
| 3 | `d4_bank_change.pdf` | HUMAN_REVIEW — `bank_account 🚨 HIGH_RISK` (XXXX9876 vs master XXXX1234) | **Approve** (after "phone verification") |
| 4 | `d5_missing_po.pdf` | EXCEPTION — `po_exists NOT_FOUND`, lines ❓ "no PO match" | **Request Info** → `info_requested`, yellow parks at reviewer |
| 5 | `d6_low_confidence.pdf` | HUMAN_REVIEW — quality `poor`, confidence capped ≤ 0.5 | **Correct** (fix a field) → pipeline re-runs automatically |
| 6 | `d7_high_value.pdf` | FINANCE_REVIEW — ¥1.2M > ¥1M band | leave open (finance approves, not you) |
| 7 | `d8_currency_mismatch.pdf` | EXCEPTION — currency FAIL (USD invoice vs JPY PO) | **Reject** |
| 8 | `d9_small.pdf` | **AUTO_APPROVE** — whole strip green ending `auto_approved`, never enters inbox | — |
| 9 | `d10_scanned.pdf` | MANAGER_REVIEW **via OCR** — image-only PDF, zero text layer, robot reads it | **Approve** |
| 10 | `d3_duplicate.pdf` | **REJECT** — blocked pre-insert (INV-10025 already paid in seed); audit event lands on the original invoice | — |

## What to verify on each

- **Banner:** decision text + rule id under the invoice title.
- **Workflow strips:** top strip (🤖 agent) should be all green once decided;
  bottom strip (🧍 human) shows where the human loop stands — yellow = waiting
  on you, green = resolved.
- **Invoice vs PO table** (under Match): ✅ mapped lines, 🚨 mismatched,
  ❓ unmapped — with exact qty/price side by side.
- **Inbox:** open exception count shrinks as you approve/reject.
- **All Invoices page:** final status per invoice after acting.
- **Audit timeline expander:** one event per stage + one per reviewer action.

## Fast path (upload all at once)

PowerShell, no clicking — `d3` deliberately last:

```powershell
Get-ChildItem data\invoices\*.pdf |
  Where-Object { $_.Name -notmatch 'd3' } |
  ForEach-Object { curl.exe -s -F "file=@$($_.FullName)" http://127.0.0.1:8000/invoices/upload }
curl.exe -s -F "file=@data\invoices\d3_duplicate.pdf" http://127.0.0.1:8000/invoices/upload
```

Then do the human actions in the UI (or via `POST /invoices/{id}/review`).

## Expected end state

| Outcome | Invoices |
|---------|----------|
| Approved (human) | d1, d4, d10 |
| Rejected (human) | d2, d8 |
| Auto-approved | d9 |
| Info requested | d5 |
| Finance-parked (open) | d7 |
| Duplicate blocked | d3 |
| Low-confidence corrected → re-decided | d6 |

**Troubleshooting:** upload says *duplicate* unexpectedly → the DB still has
rows from a previous run; repeat the Setup step. *Cannot reach API* in the UI →
API not running or port differs (set `DOCFLOW_API` or edit the sidebar base).