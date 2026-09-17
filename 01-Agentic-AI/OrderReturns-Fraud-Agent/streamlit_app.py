"""Streamlit UI for the Return & Fraud Prevention Agent.

Drives the FastAPI backend (``app/main.py``) end-to-end:

- **Customer view** — start a new return (order picker from ``GET /orders``),
  track/continue a return by thread_id (incl. the photo-resubmit loop).
- **Manager view** — pending-approvals queue with approve/reject actions,
  plus an optional all-returns table with a status filter.
- **Pipeline view** — fleet board of every return across the agent's 7-step
  state machine: completed / active / not-started stages per return, plus
  the node-by-node audit trail from ``decision_log``.

No auth, no image upload, no auto-polling — manual refresh buttons only,
matching the backend's synchronous request/response style.

Run (from the ``return-agent/`` directory, backend already up on :8765)::

    streamlit run streamlit_app.py
"""
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
import streamlit as st

from workflow_ui import (
    photo_sub_label,
    render_workflow_selector,
    render_workflow_track,
    _STAGE_LEGEND,
)

st.set_page_config(
    page_title="Return & Fraud Prevention Agent",
    page_icon="📦",
    layout="wide",
)

#: Status -> UI badge color (Streamlit status widgets / markdown chips).
_STATUS_COLORS: Dict[str, str] = {
    "pending": "🔵",
    "awaiting_photo": "🟡",
    "awaiting_approval": "🟠",
    "approved": "🟢",
    "completed": "✅",
    "rejected": "🔴",
    "denied_policy": "⛔",
}

_ALL_STATUSES = [
    "pending",
    "awaiting_photo",
    "awaiting_approval",
    "approved",
    "rejected",
    "completed",
    "denied_policy",
]


# ---------------------------------------------------------------------------
# HTTP helpers — never raise; return None on failure so callers can guard.
# ---------------------------------------------------------------------------
def api_get(path: str) -> Optional[Any]:
    """GET ``{api_base}{path}``; show st.error and return None on failure."""
    base = st.session_state.get("api_base", "http://127.0.0.1:8765").rstrip("/")
    try:
        resp = httpx.get(f"{base}{path}", timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        st.error(f"API {path} → HTTP {exc.response.status_code}: {detail}")
        return None
    except Exception as exc:
        st.error(f"API GET {path} failed: {exc}")
        return None


def api_post(path: str, json: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """POST ``{api_base}{path}``; show st.error and return None on failure."""
    base = st.session_state.get("api_base", "http://127.0.0.1:8765").rstrip("/")
    try:
        resp = httpx.post(f"{base}{path}", json=json or {}, timeout=60.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("detail", exc.response.text)
        st.error(f"API {path} → HTTP {exc.response.status_code}: {detail}")
        return None
    except Exception as exc:
        st.error(f"API POST {path} failed: {exc}")
        return None


def status_chip(status: str) -> str:
    """Markdown chip like ``🟠 awaiting_approval``."""
    return f"{_STATUS_COLORS.get(status, '⚪')} `{status}`"


def format_money(value: Optional[float]) -> str:
    """``$899.00`` or ``—`` when None."""
    return f"${value:,.2f}" if value is not None else "—"


#: Fraud flag -> (plain-English rule, weight added to the score).
_FRAUD_RULES: Dict[str, Tuple[str, float]] = {
    "high_return_velocity": ("customer has ≥ 3 returns in the last 30 days", 0.4),
    "no_photo_proof": ("damaged claim with no photo after retries exhausted", 0.4),
    "high_refund_amount": ("refund amount > \\$500", 0.3),
}

_CONDITION_LABELS: Dict[str, str] = {
    "damaged_defective": "🩹 Damaged / Defective",
    "buyer_remorse": "🛍️ Buyer's Remorse",
    "unknown": "❓ Not classified yet",
}


def _classify_detail(log: List[str]) -> Optional[str]:
    """The '(...)' detail from the newest 'classified as' audit entry.

    E.g. ``LLM classifier: gpt-oss:120b`` or ``keyword fallback
    classifier (LLM unavailable or unparseable)``.
    """
    for entry in reversed(log or []):
        if "classified as" in entry:
            start = entry.rfind("(")
            end = entry.rfind(")")
            if start != -1 and end != -1 and end > start:
                return entry[start + 1 : end]
    return None


def render_fraud_math(r: Dict[str, Any]) -> None:
    """Show how the fraud score was built: rule × weight per flag + triggers."""
    score = r.get("fraud_score")
    if score is None:
        st.caption("Fraud not computed yet (workflow hasn't reached the fraud check).")
        return

    flags = r.get("fraud_flags") or []
    lines = ["**Base score 0.00**"]
    for flag in flags:
        rule, weight = _FRAUD_RULES.get(flag, (flag, 0.0))
        lines.append(f"- `{flag}` → **+{weight:.2f}** — {rule}")
    if not flags:
        lines.append("- no fraud rules triggered → +0.00")
    lines.append(
        f"**Total = {score:.2f}** (manager gate at ≥ 0.70, "
        "or refund > \\$200)"
    )
    st.info("\n".join(lines), icon="🧮")


# ---------------------------------------------------------------------------
# Sidebar — API base URL + view switch
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Settings")
    st.session_state["api_base"] = st.text_input(
        "API base URL",
        value=st.session_state.get("api_base", "http://127.0.0.1:8765"),
        help="Backend must be running here (uvicorn app.main:app --port 8765).",
    )
    view = st.radio("View", ["Customer", "Manager", "Pipeline"], horizontal=True)
    st.caption("No auth — demo console for the LangGraph return agent.")


# ---------------------------------------------------------------------------
# Customer view
# ---------------------------------------------------------------------------
def customer_view() -> None:
    st.header("🛍️ Customer — start or track a return")

    left, right = st.columns(2, gap="large")

    # ---- Start a new return -------------------------------------------------
    with left:
        st.subheader("Start a new return")
        orders = st.session_state.get("orders")
        if orders is None:
            orders = api_get("/orders")
            st.session_state["orders"] = orders

        if not orders:
            st.warning("No orders available (is the backend running?).")
        else:
            def order_label(o: Dict[str, Any]) -> str:
                return (
                    f"{o['order_id']} — {o['item_name']} "
                    f"(${o['item_value']:,.2f}, ordered {o['order_date']})"
                )

            choice = st.selectbox(
                "Order", orders, format_func=order_label, index=None,
                placeholder="Pick the order to return…",
            )
            if choice is not None:
                st.caption(
                    f"Item: `{choice['item_id']}` · Value: "
                    f"**{format_money(choice['item_value'])}** · "
                    f"Ordered: {choice['order_date']}"
                )
                reason = st.text_area("Reason for return")
                photo_provided = st.checkbox("I can provide a photo")
                photo_url = None
                if photo_provided:
                    photo_url = st.text_input("Photo URL")

                if st.button("Submit return", type="primary", use_container_width=True):
                    if not reason.strip():
                        st.error("Please describe the reason for the return.")
                    else:
                        resp = api_post(
                            "/returns",
                            json={
                                "order_id": choice["order_id"],
                                "item_id": choice["item_id"],
                                "reason_text": reason.strip(),
                                "photo_provided": photo_provided,
                                "photo_url": photo_url,
                            },
                        )
                        if resp is not None:
                            st.session_state["last_thread_id"] = resp["thread_id"]
                            st.session_state["last_response"] = resp
                            st.rerun()

            # Result of the last submission
            last = st.session_state.get("last_response")
            if last is not None:
                st.divider()
                st.markdown(f"**Thread ID:** `{last['thread_id']}`")
                render_return_details(last)

    # ---- Track / continue a return ------------------------------------------
    with right:
        st.subheader("Track / continue a return")
        default_tid = st.session_state.get("last_thread_id", "")
        thread_id = st.text_input(
            "Thread ID", value=default_tid, placeholder="uuid4 from a previous run"
        )
        b1, b2 = st.columns(2)
        refresh = b1.button("🔄 Refresh status", use_container_width=True)
        track = b2.button("Look up", type="primary", use_container_width=True)

        if (refresh or track) and thread_id.strip():
            current = api_get(f"/returns/{thread_id.strip()}")
            if current is not None:
                st.session_state["tracked"] = current

        tracked = st.session_state.get("tracked")
        if tracked is not None:
            render_return_details(tracked)

            # Photo-resubmit loop when paused at the photo gate
            if tracked["status"] == "awaiting_photo":
                st.info("📷 This return needs photo proof before the refund can proceed.")
                new_photo = st.checkbox("I have a photo this time")
                new_url = st.text_input("Photo URL") if new_photo else None
                if st.button("Submit photo", type="primary"):
                    resp = api_post(
                        f"/returns/{tracked['thread_id']}/photo",
                        json={"photo_provided": new_photo, "photo_url": new_url},
                    )
                    if resp is not None:
                        st.session_state["tracked"] = resp
                        st.rerun()


def render_return_details(r: Dict[str, Any]) -> None:
    """Status, message, computed fields and next action for one return."""
    st.markdown(f"### {status_chip(r['status'])}")
    st.write(r["message"])
    st.caption(
        f"Order `{r.get('order_id')}` · Item `{r.get('item_id')}` · "
        f"Reason: *{r.get('reason_text')}*"
    )

    # --- Workflow selector: all 4 paths, active one enabled, rest greyed ---
    render_workflow_selector(r)
    render_workflow_track(stage_statuses(r), subs={"Photo": photo_sub_label(r)})

    # --- AI classification: what did the LLM decide? -----------------------
    condition = r.get("item_condition")
    detail = _classify_detail(r.get("decision_log") or [])
    ai_line = f"🤖 **AI classification:** {_CONDITION_LABELS.get(condition, condition or '—')}"
    if detail:
        ai_line += f" — via *{detail}*"
    st.markdown(ai_line)
    st.caption(
        "Damaged/defective → \\$0.00 shipping fee + photo proof required · "
        "Buyer's remorse → flat \\$5.99 shipping fee."
    )

    cols = st.columns(4)
    cols[0].metric("Refund", format_money(r.get("refund_amount")))
    cols[1].metric("Shipping fee", format_money(r.get("shipping_fee")))
    cols[2].metric("Fraud score", r.get("fraud_score") if r.get("fraud_score") is not None else "—")
    cols[3].metric("Next action", r.get("next_action") or "none")

    flags = r.get("fraud_flags") or []
    if flags:
        st.warning("Fraud flags: " + ", ".join(f"`{f}`" for f in flags))
        render_fraud_math(r)
    if r.get("manager_note"):
        st.info(f"Manager note: {r['manager_note']}")


# ---------------------------------------------------------------------------
# Manager view
# ---------------------------------------------------------------------------
def _invalidate_return_caches() -> None:
    """Drop cached queue/list data so the next render refetches from the API."""
    st.session_state.pop("pending_queue", None)
    st.session_state.pop("pipeline_rows", None)
    for key in list(st.session_state.keys()):
        if key.startswith("all_returns_"):
            del st.session_state[key]


def manager_view() -> None:
    st.header("🧑‍💼 Manager console")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Pending approvals")
        if st.button("🔄 Refresh queue", key="refresh_queue"):
            st.session_state.pop("pending_queue", None)

        # Outcome of the last approve/reject (survives the st.rerun below).
        last_result = st.session_state.pop("manager_result", None)
        if last_result:
            st.success(last_result)

        if "pending_queue" not in st.session_state:
            st.session_state["pending_queue"] = (
                api_get("/returns?status=awaiting_approval") or []
            )
        pending = st.session_state["pending_queue"]

        if not pending:
            st.success("No returns awaiting approval. 🎉")
        else:
            for r in pending:
                with st.expander(
                    f"{status_chip(r['status'])} · {r.get('order_id')} · "
                    f"refund {format_money(r.get('refund_amount'))} · "
                    f"`{r['thread_id'][:8]}…`"
                ):
                    st.caption(
                        f"Item `{r.get('item_id')}` · Reason: *{r.get('reason_text')}*"
                    )
                    # Workflow selector + node/line stepper for this return
                    render_workflow_selector(r)
                    render_workflow_track(
                        stage_statuses(r), subs={"Photo": photo_sub_label(r)}
                    )
                    detail = _classify_detail(r.get("decision_log") or [])
                    condition = r.get("item_condition")
                    ai_line = f"🤖 AI: **{_CONDITION_LABELS.get(condition, condition or '—')}**"
                    if detail:
                        ai_line += f" · *{detail}*"
                    st.caption(ai_line)
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Refund", format_money(r.get("refund_amount")))
                    m2.metric("Fraud score", r.get("fraud_score"))
                    m3.metric("Flags", ", ".join(r.get("fraud_flags") or []) or "none")
                    render_fraud_math(r)

                    note = st.text_input(
                        "Manager note", key=f"note_{r['thread_id']}"
                    )
                    a, rej = st.columns(2)
                    if a.button("✅ Approve", key=f"approve_{r['thread_id']}"):
                        resp = api_post(
                            f"/returns/{r['thread_id']}/approve",
                            json={"manager_note": note or None},
                        )
                        if resp is not None:
                            st.session_state["manager_result"] = (
                                f"✅ Approved `{r['thread_id'][:8]}…` → "
                                f"**{resp['status']}** "
                                f"(refund {format_money(resp.get('refund_amount'))})"
                            )
                            _invalidate_return_caches()
                            st.rerun()
                    if rej.button("❌ Reject", key=f"reject_{r['thread_id']}"):
                        resp = api_post(
                            f"/returns/{r['thread_id']}/reject",
                            json={"manager_note": note or None},
                        )
                        if resp is not None:
                            st.session_state["manager_result"] = (
                                f"❌ Rejected `{r['thread_id'][:8]}…` → "
                                f"**{resp['status']}**"
                            )
                            _invalidate_return_caches()
                            st.rerun()

    with col2:
        st.subheader("All returns")
        filter_status = st.selectbox(
            "Filter by status", ["(all)"] + _ALL_STATUSES
        )
        if st.button("🔄 Refresh list", key="refresh_all"):
            st.session_state.pop("all_returns", None)

        cache_key = f"all_returns_{filter_status}"
        if cache_key not in st.session_state:
            path = (
                "/returns"
                if filter_status == "(all)"
                else f"/returns?status={filter_status}"
            )
            st.session_state[cache_key] = api_get(path) or []
        rows = st.session_state[cache_key]

        if rows:
            table = [
                {
                    "Thread": r["thread_id"][:8] + "…",
                    "Status": r["status"],
                    "Order": r.get("order_id"),
                    "Item": r.get("item_id"),
                    "Refund": format_money(r.get("refund_amount")),
                    "Fraud": r.get("fraud_score") if r.get("fraud_score") is not None else "—",
                }
                for r in rows
            ]
            st.dataframe(table, use_container_width=True, hide_index=True)
        else:
            st.info("No returns match this filter.")


# ---------------------------------------------------------------------------
# Pipeline view — fleet board across the agent's 7-step state machine
# ---------------------------------------------------------------------------
PIPELINE_STAGES = ["Policy", "Classify", "Photo", "Fee", "Fraud", "Manager", "Refund"]


def stage_statuses(r: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Derive per-stage state for one return from its status + decision_log.

    Stage states: done / active / pending / skip / fail — colours are applied
    by ``workflow_ui.render_workflow_track``.
    """
    log = r.get("decision_log") or []
    text = " | ".join(log)
    status = r["status"]

    photo_needed = "photo proof required" in text
    gate_needed = "manager approval required" in text
    denied = status == "denied_policy"

    # Policy denies short-circuit the graph — every later stage is skipped.
    if denied:
        return [(s, "fail" if s == "Policy" else "skip") for s in PIPELINE_STAGES]

    policy = "done" if (
        "validated" in text or "not found" in text or "outside the" in text
    ) else "pending"
    classify = "done" if "classified as" in text else "pending"

    if photo_needed:
        if status == "awaiting_photo":
            photo = "active"
        elif "photo resubmission" in text or "retries exhausted" in text:
            photo = "done"
        else:
            photo = "pending"
    else:
        photo = "skip"  # not a damaged claim / photo already attached

    fee = "done" if "shipping fee" in text else "pending"
    fraud = "done" if "fraud score" in text else "pending"

    if status == "awaiting_approval":
        manager = "active"
    elif not gate_needed:
        manager = "skip"  # low-risk refund — no human gate on this path
    elif status == "rejected":
        manager = "fail"
    else:  # approved/completed after passing the gate
        manager = "done"

    if "processed successfully" in text:
        refund = "done"
    elif status == "rejected":
        refund = "skip"  # no refund issued
    else:
        refund = "pending"

    return list(zip(
        PIPELINE_STAGES,
        [policy, classify, photo, fee, fraud, manager, refund],
    ))


def _photo_attempt_detail(r: Dict[str, Any]) -> Optional[str]:
    """``attempt 2/3`` from the newest photo log entry, or None."""
    match = None
    for entry in r.get("decision_log") or []:
        match = re.search(r"attempt (\d+)/(\d+)", entry)
    return f"attempt {match.group(1)}/{match.group(2)}" if match else None


def render_pipeline_card(r: Dict[str, Any]) -> None:
    """One return: workflow selector + node/line stepper + audit trail."""
    tid = r["thread_id"]
    is_active = r["status"] in ("awaiting_photo", "awaiting_approval")
    with st.expander(
        f"{status_chip(r['status'])} · {r.get('order_id')} · "
        f"{format_money(r.get('refund_amount'))} · `{tid[:8]}…`",
        expanded=is_active,
    ):
        st.caption(f"Item `{r.get('item_id')}` · Reason: *{r.get('reason_text')}*")

        render_workflow_selector(r)
        stages = stage_statuses(r)
        condition = r.get("item_condition")
        detail = _classify_detail(r.get("decision_log") or [])
        ai_line = f"🤖 AI classified as **{_CONDITION_LABELS.get(condition, condition or '—')}**"
        if detail:
            ai_line += f" · *{detail}*"
        st.caption(ai_line)

        render_workflow_track(stages, subs={"Photo": photo_sub_label(r)})

        active_stage = next((n for n, s in stages if s == "active"), None)
        if active_stage == "Photo":
            detail = _photo_attempt_detail(r)
            suffix = f" ({detail})" if detail else ""
            st.info(f"🔵 Now: **{active_stage}** — waiting for the customer to submit photo proof{suffix}.")
        elif active_stage == "Manager":
            st.info(
                f"🔵 Now: **{active_stage}** — waiting for a manager decision "
                f"(refund {format_money(r.get('refund_amount'))}). Resolve it in the **Manager** view."
            )

        st.markdown("**Completed activities (audit trail)**")
        log = r.get("decision_log") or []
        if log:
            for i, entry in enumerate(log, 1):
                st.markdown(f"{i}. {entry}")
        else:
            st.caption("No activity recorded yet.")


def pipeline_view() -> None:
    st.header("🔄 Workflow pipeline")
    st.caption(
        "Stage status per return across the agent state machine. " + _STAGE_LEGEND,
        unsafe_allow_html=True,
    )

    if st.button("🔄 Refresh", key="refresh_pipeline"):
        st.session_state.pop("pipeline_rows", None)

    if "pipeline_rows" not in st.session_state:
        st.session_state["pipeline_rows"] = api_get("/returns") or []
    rows = st.session_state["pipeline_rows"]

    if not rows:
        st.info("No returns yet — start one in the **Customer** view.")
        return

    active = [r for r in rows if r["status"] in ("awaiting_photo", "awaiting_approval")]
    done = [r for r in rows if r["status"] in ("completed", "approved")]
    closed_bad = [r for r in rows if r["status"] in ("rejected", "denied_policy")]

    m = st.columns(5)
    m[0].metric("🟡 Awaiting photo", len([r for r in active if r["status"] == "awaiting_photo"]))
    m[1].metric("🟠 Awaiting approval", len([r for r in active if r["status"] == "awaiting_approval"]))
    m[2].metric("✅ Completed", len(done))
    m[3].metric("🔴 Rejected", len([r for r in closed_bad if r["status"] == "rejected"]))
    m[4].metric("⛔ Denied", len([r for r in closed_bad if r["status"] == "denied_policy"]))

    for title, group in (
        ("🔵 Active — needs a human right now", active),
        ("✅ Completed", done),
        ("🔴 Rejected / ⛔ Denied", closed_bad),
    ):
        if not group:
            continue
        st.subheader(f"{title} ({len(group)})")
        for r in group:
            render_pipeline_card(r)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
if view == "Customer":
    customer_view()
elif view == "Pipeline":
    pipeline_view()
else:
    manager_view()