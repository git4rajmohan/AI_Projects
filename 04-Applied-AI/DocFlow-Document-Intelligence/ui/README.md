# Reviewer UI (Phase 11)

Streamlit app over the FastAPI backend. Reviewer sees the document, extracted
fields, validation, match, and policy reasons before acting (§12 evidence-first).

## Run

```bash
# terminal 1 — API
.venv/Scripts/python.exe -m uvicorn app.api.main:app --port 8000

# terminal 2 — UI
.venv/Scripts/python.exe -m streamlit run ui/reviewer.py
```

UI defaults to `http://127.0.0.1:8000` (override with `DOCFLOW_API` env var or the
sidebar input). Extraction defaults to mock mode (`.env`), so uploads of the
shipped samples need no Ollama.

## Manual smoke checklist (§11.4)

| # | Step | Expected |
|---|------|----------|
| 1 | Start API + UI, open browser | "Review Inbox" shows "No open exceptions"; health OK |
| 2 | All Invoices → Upload `data/invoices/d1_normal.pdf` → Run pipeline | caption shows `decision=MANAGER_REVIEW`, `status=in_review` |
| 3 | Open `d1_normal` from list | PDF renders left; extraction/validation/match checks + reasons on the right; audit timeline lists received→extracted→validated→matched→policy_decided→in_review |
| 4 | Upload `d9_small.pdf` | `decision=AUTO_APPROVE`, no exception row |
| 5 | Upload `d2_qty_mismatch.pdf` | appears in Review Inbox (policy_exception, open) |
| 6 | Inbox → select `d2_qty_mismatch` → enter reviewer name → Approve with comment | status becomes `approved`; exception resolved; row gone from inbox |
| 7 | Upload `d4_bank_change.pdf` → Reject | status `rejected`, reason R002-bank-change visible before acting |
| 8 | Upload `d6_low_confidence.pdf` → Correct & Resubmit with corrected `total_amount` | pipeline re-runs; corrected field confidence 1.0; status reflects new decision |
| 9 | Upload `d3_duplicate.pdf` | caption shows `decision=REJECT`; invoice not added to the list |
| 10 | Request Info on any review item | status `info_requested`, stays out of approve lists |