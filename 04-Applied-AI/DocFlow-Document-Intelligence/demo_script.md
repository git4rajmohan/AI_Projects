# DocFlow demo script — the 5 demo flows (Instructions §22)

All demos work offline in mock extraction mode (`.env` ships
`EXTRACTION_MODE=mock`), which replays each sample's ground-truth fields — the
AI interpretation step is stubbed; validation/matching/policy stay fully live.

```bash
# terminal 1 — API
.venv/Scripts/python.exe -m uvicorn app.api.main:app --port 8000

# terminal 2 — reviewer UI (optional; demos run via API or UI)
.venv/Scripts/python.exe -m streamlit run ui/reviewer.py
```

Or run the whole suite headlessly:
`.venv/Scripts/python.exe -m evaluation.run_eval` (all decisions below verified
in `evaluation/report.md`).

---

## Demo 1 — Normal Invoice (`data/invoices/d1_normal.pdf`)

```text
Upload invoice
   ↓
Extract fields        received → extracted
   ↓
Validate              all 9 checks PASS (vendor active, bank XXXX1234 = master,
   ↓                  arithmetic exact, no duplicate, date sane)
Two-way match         po_exists/vendor/line_mapping/quantity/unit_price/total all MATCH
   ↓                  (three-way: receipts 100/150 = invoiced → PASS)
Policy check          R007-manager-limit: ¥850,000 ≥ ¥100,000 → MANAGER_REVIEW
   ↓
in_review (manager queue)
```

Expected decision: **MANAGER_REVIEW**. Approve it as a reviewer
(`POST /invoices/d1_normal/review` with `{"reviewer": "yuki", "action": "approve"}`)
→ status `approved`, open exceptions resolved, action recorded in the audit.

## Demo 2 — Quantity Mismatch (`d2_qty_mismatch.pdf`)

```text
Upload invoice
   ↓
Extract               line "Product A" qty 150 (PO says 100)
   ↓
PO quantity mismatch  match check quantity → MISMATCH
   ↓
Exception             R004-mismatch → EXCEPTION → status in_review
   ↓                  exceptions row: policy_exception, "quantity mismatched"
Human review          reviewer sees MISMATCH evidence in the UI
```

Expected decision: **EXCEPTION**. Reviewer action: Approve after verifying the
GR, Reject, or Correct the quantity (`corrections: {"line_items": [...]}`) →
pipeline re-runs from validation (§8.5).

## Demo 3 — Duplicate Invoice (`d3_duplicate.pdf`)

```text
Upload invoice
   ↓
Extract invoice number INV-10025 — already recorded (paid, inv_seed_1)
   ↓
Duplicate detected    R001-duplicate → REJECT
   ↓
Block automatic approval  never stored, never matched, never approved;
   ↓                  audit event duplicate_blocked lands on the original invoice
Human investigation   investigator pulls the audit trail of inv_seed_1
```

Expected decision: **REJECT**. Re-uploading an already-processed invoice is also
blocked the same way (idempotency, §8.6).

## Demo 4 — Changed Bank Account (`d4_bank_change.pdf`)

```text
Upload invoice
   ↓
Vendor validation     bank_account check → HIGH_RISK (XXXX9876 vs master XXXX1234)
   ↓
HIGH-RISK EXCEPTION   R002-bank-change → HUMAN_REVIEW (mandatory, §10)
   ↓                  exceptions row: high_risk
Human verification    reviewer compares the PDF's bank account against the
                      vendor master before any approve/reject
```

Expected decision: **HUMAN_REVIEW**. Nothing auto-approves a bank change, ever.

## Demo 5 — Low Confidence (`d6_low_confidence.pdf`)

```text
Poor-quality scan     ingest marks quality="poor" (degraded sample)
   ↓
AI extraction confidence = low  (critical fields capped ≤ 0.5)
   ↓
Human review          R005-low-confidence → HUMAN_REVIEW, in_review
   ↓
Correct field         reviewer posts corrections, e.g.
                      {"total_amount": 40000} → field_confidence set to 1.0
   ↓
Resume workflow       pipeline re-runs from validation; corrected doc gets a
                      fresh decision (still in_review if other fields stay low)
```

Expected decision: **HUMAN_REVIEW** before and after a partial correction —
correcting one field doesn't launder the rest; a full correction of the
low-confidence fields can reach a final decision.

---

## Also worth 30 seconds

- `d9_small.pdf` — ¥60k invoice → **AUTO_APPROVE** (R008), end-to-end with no
  human. This is the "review time saved" story.
- `d7_high_value.pdf` — ¥1.2M → **FINANCE_REVIEW** (R006).
- `d8_currency_mismatch.pdf` — USD invoice vs JPY PO → **EXCEPTION**.
- `d10_scanned.pdf` — image-only scan, zero text layer → OCR (auto mode) reads
  it back and it flows like Demo 1 (MANAGER_REVIEW). Without Tesseract installed
  it degrades to poor-quality → HUMAN_REVIEW. Both paths are safe by design.
- Upload a corrupt PDF to `POST /invoices/upload` → HTTP 422 + an `ingest_error`
  exception row + `ingest_failed` audit event (§10.3).

Every decision is reconstructable: `GET /invoices/{id}/audit` returns the full
ordered event story (received → extracted → validated → matched →
policy_decided → outcome → reviewer actions). Demo 1's trail ships as
`evaluation/demo1_audit.json`.