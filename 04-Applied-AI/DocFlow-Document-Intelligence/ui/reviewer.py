"""Phase 11 — Streamlit reviewer UI.

Evidence-first (§12): the reviewer sees the document, extracted fields,
validation, match and the policy decision *before* any action. Thin client over
the Phase 10 API — no direct DB access, so API and UI can live on different hosts.
"""
import os

import requests
import streamlit as st

st.set_page_config(page_title="DocFlow Reviewer", layout="wide")

API = st.sidebar.text_input("API base", os.environ.get("DOCFLOW_API", "http://127.0.0.1:8000"))
REVIEWER = st.sidebar.text_input("Reviewer name")
PAGE = st.sidebar.radio("Page", ["Review Inbox", "All Invoices"])

ICON = {"PASS": "✅", "MATCH": "✅", "FAIL": "❌", "HIGH_RISK": "🚨", "DUPLICATE": "🚨",
        "MISMATCH": "❌", "NOT_FOUND": "❌", "WARN": "⚠️", "SKIP": "➖"}


def api(method: str, path: str, **kw) -> dict:
    try:
        r = requests.request(method, f"{API}{path}", timeout=30, **kw)
    except requests.ConnectionError as e:
        st.error(f"Cannot reach API at {API} — start it with "
                 "`uvicorn app.api.main:app --port 8000` (or fix the sidebar base URL).")
        st.stop()
    if r.status_code >= 400:
        st.error(f"{method} {path} → {r.status_code}: {r.text[:300]}")
        st.stop()
    return r.json()


def checks_block(rows: list[dict]) -> None:
    for c in rows or []:
        st.markdown(f"- {ICON.get(c['status'], '•')} `{c['name']}` **{c['status']}** — {c['detail']}")


def line_compare(d: dict) -> None:
    """Side-by-side: each invoice line vs its matched PO line (qty / price).
    Rows come only from data already in the API payload — no recomputation."""
    ext = d.get("extraction") or {}
    inv_lines = ext.get("line_items") or []
    if not inv_lines:
        return
    st.markdown("##### Invoice vs PO — per line")
    # JSON object keys arrive as strings on both dicts — coerce to int so the
    # line_map values find their po_lines rows.
    po_lines = {int(k): v for k, v in (d.get("po_lines") or {}).items()}
    line_map = {int(k): v for k, v in (d.get("line_map") or {}).items()}
    # flag strings from the match checks, keyed by description fragment
    flags = {c["detail"]: c["status"] for c in d.get("match", [])
             if c["name"] in ("quantity", "unit_price", "line_mapping")
             and c["status"] in ("MISMATCH", "NOT_FOUND")}
    rows = []
    for i, li in enumerate(inv_lines):
        po = po_lines.get(line_map.get(i))
        # find the specific mismatch detail mentioning this description, if any
        detail = next((det for det in flags if li["description"] in det), "")
        if po:
            rows.append({
                "": "🚨" if detail else "✅",
                "Invoice line": li["description"],
                "Qty": f"{li['quantity']:g}",
                "PO Qty": f"{po['quantity']:g}",
                "Inv price": f"{li['unit_price']:g}",
                "PO price": f"{po['unit_price']:g}",
                "Flag": detail or "matches PO",
            })
        else:
            rows.append({
                "": "❓",
                "Invoice line": li["description"],
                "Qty": f"{li['quantity']:g}", "PO Qty": "—",
                "Inv price": f"{li['unit_price']:g}", "PO price": "—",
                "Flag": detail or "no PO match",
            })
    st.dataframe(rows, use_container_width=True, hide_index=True)


PIPELINE = ["received", "extracted", "validated", "matched", "policy_decided"]
TERMINALS = {  # decision -> post-policy states this invoice flows through
    "AUTO_APPROVE": ["auto_approved"],
    "REJECT": ["rejected"],
    "EXCEPTION": ["in_review"],
    "HUMAN_REVIEW": ["in_review"],
    "MANAGER_REVIEW": ["in_review"],
    "FINANCE_REVIEW": ["in_review"],
}
# final DB status -> the loop strip's last stage label (what "resolved" means)
DONE_STATUS = {"approved": "✅ approved", "rejected": "❌ rejected",
               "auto_approved": "✅ auto_approved", "info_requested": "⏸ info_requested"}
GREEN, YELLOW, GREY = "#1c7a35", "#c9a227", "#3a3f44"
# done / active / not-started pill + arrow — one HTML blob, no JS, no package.
# Robot SVG marks agent steps, 🧍 marks human steps (§21 responsibility table).
# Inline SVG over an emoji: renders identically everywhere, never falls back
# to a monochrome text glyph.
PILL = ('<span style="background:{c};color:#fff;padding:3px 10px;border-radius:12px;'
        'font-size:0.78em;font-weight:600;white-space:nowrap">{label}</span>')
ARROW = ('<span style="color:{c};font-size:0.9em;padding:0 2px">'
         '{a}</span>')
ROBOT = ('<svg width="12" height="12" viewBox="0 0 24 24" fill="none" '
         'stroke="#fff" stroke-width="2" style="vertical-align:-2px;margin-right:3px">'
         '<rect x="5" y="8" width="14" height="10" rx="2"/>'
         '<line x1="12" y1="8" x2="12" y2="4"/>'
         '<circle cx="12" cy="3" r="1.4" fill="#fff" stroke="none"/>'
         '<circle cx="9.5" cy="13" r="1.4" fill="#fff" stroke="none"/>'
         '<circle cx="14.5" cy="13" r="1.4" fill="#fff" stroke="none"/>'
         '</svg>')
AGENT_STEPS = {"received", "extracted", "validated", "matched", "policy_decided",
               "auto_approved", "rejected", "ingest_failed"}
HUMAN_STEPS = {"in_review", "reviewer action", "info_requested", "resolved"}
ICONS = {**{s: ROBOT for s in AGENT_STEPS}, **{s: "🧍 " for s in HUMAN_STEPS}}

# §13 explainability per stage — hover text on each workflow pill
TOOLTIP = {
    "received": "Document saved + OCR/text layer read; quality graded (ok/poor)",
    "extracted": "AI read the document into structured fields with per-field confidence",
    "validated": "Code verified vendor, required fields, arithmetic, duplicate, dates, bank account",
    "matched": "Invoice lines mapped to PO lines; qty/price/tolerance compared in code",
    "policy_decided": "Deterministic rules R001-R008 applied — thresholds, exceptions, risk bands",
    "auto_approved": "Under the auto-approve limit with all checks green — no human needed",
    "rejected": "Blocked by policy (e.g. duplicate) — never approved, trail kept for audit",
    "ingest_failed": "Document unreadable — exception row created for investigation",
    "in_review": "Waiting for a human reviewer — evidence shown below",
    "reviewer action": "Reviewer chooses: approve, reject, correct & resubmit, or request info",
    "info_requested": "Parked until the requested information arrives",
    "resolved": "Human decision recorded in the audit trail — workflow complete",
}


def _strip(stages: list[str], done_until: int, active: bool) -> str:
    parts = []
    for i, s in enumerate(stages):
        icon = ICONS.get(s, "")
        if i < done_until or (i == done_until and not active):
            color, label = GREEN, f"✓ {icon}{s}"
        elif i == done_until:
            color, label = YELLOW, f"▶ {icon}{s}"
        else:
            color, label = GREY, f"{icon}{s}"
        tip = TOOLTIP.get(s, s.replace("_", " "))
        parts.append(f'<span title="{tip}" ' + PILL.format(c=color, label=label)[6:])
        if i < len(stages) - 1:
            parts.append(ARROW.format(c=color, a="→"))
    return "".join(parts)


def workflow_viz(d: dict, events: list[dict]) -> None:
    """Two colored strips: where this invoice sits in the pipeline + review loop."""
    done = {e["stage"] for e in events}
    last = max((PIPELINE.index(e["stage"]) for e in events
                if e["stage"] in PIPELINE), default=-1)
    terminal = TERMINALS.get(d.get("decision") or "", ["in_review"])
    # strip 1: pipeline stages, all green once policy decided; if parked mid-way
    # (e.g. ingest_failed), remaining stages show grey
    p_done = last + 1 if done & {s for s in PIPELINE} else 0
    active1 = d["status"] in PIPELINE  # still moving vs parked at a final-ish state
    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:2px">'
        + _strip(PIPELINE + terminal, len(PIPELINE) if p_done == len(PIPELINE) else p_done,
                 active1) + "</div>", unsafe_allow_html=True)
    # strip 2: human loop — shown whenever the invoice has passed policy (the
    # reviewer may still act from the All Invoices page even after resolution)
    if d["status"] in ("in_review", "info_requested", "approved", "rejected",
                       "auto_approved"):
        last_label = DONE_STATUS.get(d["status"], "resolved")
        loop = ["in_review", "reviewer action", last_label]
        if d["status"] == "info_requested":
            i_done, active = 1, True  # waiting on info — reviewer step active
        elif d["status"] in ("approved", "rejected", "auto_approved"):
            i_done, active = 2, False  # resolved — all green, nothing active
        else:
            i_done, active = 0, True  # parked in review — awaiting the human
        st.markdown(
            '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:2px;'
            'margin-top:4px">' + _strip(loop, i_done, active) + "</div>",
            unsafe_allow_html=True)
        st.caption("🤖 robot icon = agent (automatic) · 🧍 = human reviewer")


def review_view(iid: str) -> None:
    d = api("GET", f"/invoices/{iid}")
    c1, c2, c3 = st.columns([3, 1, 1])
    c1.subheader(f"Invoice {iid}")
    c2.markdown(f"**status:** `{d['status']}`")
    c3.markdown(f"**decision:** `{d.get('decision')}`")
    for r in d.get("reasons", []):
        st.markdown(f"- {r}")
    workflow_viz(d, api("GET", f"/invoices/{iid}/audit")["events"])
    st.divider()

    left, right = st.columns(2)
    with left:
        st.markdown("##### Original document")
        # Chrome blocks cross-origin AND data:-URI PDF iframes (UI :8501 →
        # API :8000 are different origins), and the API host may not even be
        # this machine — so render page 1 to PNG server-side (PyMuPDF) and
        # show it as an image. Always paints; full PDF still downloadable
        # via GET /invoices/{id}/document.
        import io

        import fitz

        pdf = requests.get(f"{API}/invoices/{iid}/document", timeout=30)
        if pdf.status_code == 200 and pdf.content[:4] == b"%PDF":
            with fitz.open(stream=pdf.content, filetype="pdf") as doc:
                st.image(doc[0].get_pixmap(dpi=150).tobytes("png"),
                         use_container_width=True)
                if doc.page_count > 1:
                    st.caption(f"page 1 of {doc.page_count}")
        else:
            st.error(f"document fetch → {pdf.status_code}")
    with right:
        st.markdown("##### Extracted fields")
        st.json(d.get("extraction") or {}, expanded=False)
        st.markdown("##### Validation")
        checks_block(d.get("validation"))
        st.markdown("##### Match")
        checks_block(d.get("match"))
        line_compare(d)
        if d.get("exceptions"):
            st.markdown("##### Exceptions")
            for e in d["exceptions"]:
                st.markdown(f"- 🚨 **{e['type']}** ({e['severity']}, {e['status']}) — {e['reason']}")
    with st.expander("Audit timeline"):
        for e in api("GET", f"/invoices/{iid}/audit")["events"]:
            st.markdown(f"- `{e['timestamp']}` **{e['stage']}**")
    if d.get("review_actions"):
        st.markdown("##### Review history")
        for a in d["review_actions"]:
            st.markdown(f"- `{a['timestamp']}` **{a['reviewer']}** {a['action']}: {a['comments']}")

    # Actions below the evidence (§12: see the why before acting)
    st.markdown("### Act")
    if not REVIEWER:
        st.info("Enter a reviewer name in the sidebar to act.")
        return
    comments = st.text_area("Comments", key=f"cmt-{iid}")
    b1, b2, b3 = st.columns(3)
    if b1.button("✅ Approve", key=f"ap-{iid}", type="primary",
                 help="Records your approval in the audit trail, resolves the open "
                      "exception, and moves the invoice to final status `approved`. "
                      "Workflow strip goes all green. Use when the evidence checks out."):
        out = api("POST", f"/invoices/{iid}/review",
                  json={"reviewer": REVIEWER, "action": "approve", "comments": comments})
        st.success(f"✅ {REVIEWER} approved {iid} — status now `{out['status']}`")
    if b2.button("❌ Reject", key=f"rj-{iid}",
                 help="Records a rejection in the audit trail and moves the invoice to "
                      "final status `rejected`. It leaves the inbox and can only be "
                      "re-tested by deleting the record. Use for real mismatches/fraud."):
        out = api("POST", f"/invoices/{iid}/review",
                  json={"reviewer": REVIEWER, "action": "reject", "comments": comments})
        st.success(f"❌ {REVIEWER} rejected {iid} — status now `{out['status']}`")
    if b3.button("❓ Request Info", key=f"ri-{iid}",
                 help="Parks the invoice at `info_requested` — it leaves the open-inbox "
                      "queue until the requested information arrives, then Correct & "
                      "Resubmit re-enters the pipeline from validation. Use when evidence "
                      "is missing (e.g. missing PO number)."):
        out = api("POST", f"/invoices/{iid}/review",
                  json={"reviewer": REVIEWER, "action": "request_info", "comments": comments})
        st.info(f"⏸ {REVIEWER} requested info on {iid} — status now `{out['status']}`")
    with st.expander("✏️ Correct & Resubmit"):
        ex = d.get("extraction") or {}
        corr: dict[str, object] = {}
        for f in ("vendor_id", "po_number", "currency", "invoice_date",
                  "total_amount", "bank_account"):
            cur = "" if ex.get(f) is None else str(ex.get(f))
            val = st.text_input(f, cur, key=f"{iid}-{f}")
            if val and val != cur:
                corr[f] = float(val) if f == "total_amount" else val
        if st.button("Submit corrections", key=f"co-{iid}",
                     help="Applies your field overrides, then re-runs the pipeline from "
                           "validation (never re-extracts). Corrected fields get full "
                           "confidence; the invoice re-decides with the fresh evidence."):
            api("POST", f"/invoices/{iid}/review",
                json={"reviewer": REVIEWER, "action": "correct", "corrections": corr,
                      "comments": comments})
            st.rerun()
    # demo re-test: remove the record so the same document can be uploaded again
    with st.expander("🗑️ Delete record (re-test)"):
        st.caption("Removes this invoice, its exceptions and audit trail — then"
                   " re-upload the same PDF for a clean run.")
        if st.button(f"🗑️ Delete {iid}", key=f"dl-{iid}",
                     help="Removes the invoice, its exceptions and audit trail from the "
                           "database. The next upload of the same PDF runs the pipeline "
                           "from scratch — for demo re-testing only."):
            out = requests.delete(f"{API}/invoices/{iid}", timeout=30)
            if out.status_code == 200:
                st.success(f"Deleted {iid} — re-upload its PDF to run again.")
                st.session_state.pop("upload_out", None)
            else:
                st.error(out.json().get("detail", f"delete → {out.status_code}"))


if PAGE == "Review Inbox":
    st.header("🚨 Exception Inbox")
    rows = api("GET", "/exceptions")
    if not rows:
        st.success("No open exceptions.")
    st.dataframe(rows)
    if rows:
        iid = st.selectbox("Review invoice", ["— choose an invoice —"] + [r["invoice_id"] for r in rows])
        if iid != "— choose an invoice —":
            review_view(iid)
else:
    st.header("Invoices")
    with st.expander("Upload an invoice PDF"):
        f = st.file_uploader("PDF", type="pdf")
        if f and st.button("Run pipeline",
                           help="Uploads the PDF and runs the full pipeline in one call: "
                                 "ingest/OCR → AI extraction → validation → PO match → "
                                 "policy decision. Result appears below; exception cases "
                                 "land in the Review Inbox."):
            st.session_state["upload_out"] = api(
                "POST", "/invoices/upload",
                files={"file": (f.name, f.getvalue(), "application/pdf")})
    if st.session_state.get("upload_out"):
        st.caption("Last upload result:")
        st.json(st.session_state.pop("upload_out"))
    status = st.selectbox("Filter status", ["All statuses", "in_review", "auto_approved",
                                            "approved", "rejected", "info_requested"])
    params = None if status == "All statuses" else {"status": status}
    rows = api("GET", "/invoices", params=params)
    st.dataframe(rows)
    if rows:
        iid = st.selectbox("Open invoice", ["— choose an invoice —"] + [r["invoice_id"] for r in rows])
        if iid != "— choose an invoice —":
            review_view(iid)