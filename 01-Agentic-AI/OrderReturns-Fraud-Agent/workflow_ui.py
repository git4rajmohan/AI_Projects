"""Workflow selector + HTML node/line workflow stepper.

Shared by the Customer and Manager views:

- **4 workflow paths** exist through the single LangGraph state machine:
  Remorse auto-complete · Photo-proof loop · Manager approval · Policy denial.
- A radio-style selector shows all 4; workflows that don't match the selected
  return are greyed out (``workflow_applicable``), matching the "highlight the
  active path, dim the others" pattern.
- :func:`render_workflow_track` draws the 7-stage path as coloured circles
  connected by lines (✅ done · 🔵 active · ⚪ pending · ⏭️ skipped · ❌
  failed) via inline HTML/CSS, mimicking a stepper like a grievance portal's
  "Type — Describe — Review" track.

No extra dependencies — plain ``st.markdown(..., unsafe_allow_html=True)``.
"""
from typing import Any, Dict, List, Optional, Tuple

import re

import streamlit as st

# ---------------------------------------------------------------------------
# Workflow catalogue — the 4 paths through the return state machine
# ---------------------------------------------------------------------------
#: key -> (icon, label, short one-line description)
WORKFLOWS: Dict[str, Tuple[str, str, str]] = {
    "remorse": (
        "🛍️",
        "Buyer's Remorse — auto-complete",
        "Low-value change-of-mind return: classified, $5.99 fee, refund paid instantly.",
    ),
    "photo": (
        "📷",
        "Damaged Item — photo-proof loop",
        "Damaged/defective claim: graph pauses until a photo is provided (≤3 tries).",
    ),
    "approval": (
        "🧑‍💼",
        "Manager Approval — human gate",
        "Refund > $200 or fraud score ≥ 0.7: pauses for a manager's decision.",
    ),
    "denial": (
        "⛔",
        "Policy Denial — auto-reject",
        "Order unknown or older than 30 days: denied immediately, nothing paid.",
    ),
}

WORKFLOW_ORDER = ["remorse", "photo", "approval", "denial"]


def _log_text(r: Dict[str, Any]) -> str:
    """Joined decision_log as one lowercase string for keyword matching."""
    return " | ".join(r.get("decision_log") or []).lower()


def _photo_retries_exhausted(r: Dict[str, Any]) -> bool:
    """True when the photo loop burned all retries without proof."""
    return "retries exhausted" in _log_text(r)


def _denied(r: Dict[str, Any]) -> bool:
    return r.get("status") == "denied_policy"


def _gated(r: Dict[str, Any]) -> bool:
    return "manager approval required" in _log_text(r)


def _needs_photo(r: Dict[str, Any]) -> bool:
    return "photo proof required" in _log_text(r)


def detect_workflow(r: Dict[str, Any]) -> str:
    """Classify one return into one of the 4 workflow paths.

    Priority: policy denial > manager gate > photo loop > remorse. A
    photo-retry exhaustion that ended at the manager gate still reports
    ``approval`` (the gate is where it sits), but keeps the photo flag so the
    stepper can show the exhausted Photo node.
    """
    if _denied(r):
        return "denial"
    if _gated(r):
        return "approval"
    if _needs_photo(r):
        return "photo"
    return "remorse"


def render_workflow_selector(r: Dict[str, Any], key_prefix: str = "") -> None:
    """Show all 4 workflows; highlight the active one, grey out the rest.

    Mirrors the reference UI: a pill list where only the selected return's
    workflow is enabled and the others are dimmed/disabled.
    """
    current = detect_workflow(r)
    # Defensive: fall back to remorse if a stale/reloaded module yields an
    # unknown key (e.g. "denied" vs "denial" during a hot-reload hiccup).
    wf = WORKFLOWS.get(current) or WORKFLOWS["remorse"]

    st.markdown(
        (
            '<div style="display:flex;align-items:center;gap:8px;margin:2px 0 6px 0;">'
            '<span style="font-size:0.95rem;font-weight:600;">Workflow</span>'
            f'<span style="font-size:0.8rem;color:#6b7280;">· this return follows: '
            f"{wf[0]} <b>{wf[1]}</b></span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    for wf_key in WORKFLOW_ORDER:
        icon, label, desc = WORKFLOWS[wf_key]
        active = wf_key == current
        if active:
            bg, border, text_c, shadow, opacity = (
                "#eef2ff", "#6366f1", "#312e81", "0 1px 4px rgba(99,102,241,.25)", "1",
            )
            badge = (
                '<span style="background:#6366f1;color:#fff;border-radius:999px;'
                'padding:1px 8px;font-size:0.7rem;font-weight:600;margin-left:8px;">'
                "SELECTED</span>"
            )
        else:
            bg, border, text_c, shadow, opacity = (
                "#f8fafc", "#e2e8f0", "#94a3b8", "none", "0.75",
            )
            badge = (
                '<span style="border:1px solid #cbd5e1;color:#94a3b8;border-radius:999px;'
                'padding:1px 8px;font-size:0.7rem;margin-left:8px;">not this path</span>'
            )
        st.markdown(
            (
                f'<div style="background:{bg};border:1px solid {border};border-radius:10px;'
                f'padding:8px 12px;margin-bottom:6px;opacity:{opacity};'
                f'box-shadow:{shadow};">'
                f'<span style="font-size:1rem;">{icon}</span> '
                f'<span style="font-weight:600;color:{text_c};font-size:0.88rem;">'
                f"{label}</span>{badge}<br/>"
                f'<span style="font-size:0.78rem;color:{text_c};">{desc}</span>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Node/line stepper (HTML circles connected by lines, like the reference UI)
# ---------------------------------------------------------------------------
_STAGE_COLORS = {
    "done": "#16a34a",    # green
    "active": "#6366f1",  # indigo — paused here right now
    "pending": "#e2e8f0", # light grey
    "skip": "#f1f5f9",    # very light grey
    "fail": "#dc2626",    # red
}
_STAGE_GLYPHS = {
    "done": "✓",
    "active": "●",
    "pending": "",
    "skip": "—",
    "fail": "✕",
}
_STAGE_LEGEND = (
    '<span style="font-size:0.78rem;color:#64748b;">'
    '<span style="color:#16a34a;">✔</span> done · '
    '<span style="color:#6366f1;">●</span> waiting here · '
    '<span style="color:#94a3b8;">○</span> not reached · '
    '<span style="color:#94a3b8;">—</span> skipped · '
    '<span style="color:#dc2626;">✕</span> failed</span>'
)


def _node_html(label: str, state: str, sub: str = "") -> str:
    """One circle node + label (+ optional sub-label) for the stepper."""
    color = _STAGE_COLORS[state]
    glyph = _STAGE_GLYPHS[state]
    dim = 'opacity:0.55;' if state in ("pending", "skip") else ""
    sub_html = (
        f'<div style="font-size:0.68rem;color:#94a3b8;margin-top:1px;">{sub}</div>'
        if sub
        else ""
    )
    return (
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'flex:1;min-width:0;{dim}">'
        f'<div style="width:30px;height:30px;border-radius:50%;background:{color};'
        f'color:#fff;display:flex;align-items:center;justify-content:center;'
        f'font-size:0.82rem;font-weight:700;'
        f'{"box-shadow:0 0 0 4px rgba(99,102,241,.18);" if state == "active" else ""}">'
        f"{glyph}</div>"
        f'<div style="font-size:0.74rem;font-weight:600;color:#334155;'
        f'margin-top:4px;white-space:nowrap;">{label}</div>'
        f"{sub_html}"
        f"</div>"
    )


def _line_html(state: str) -> str:
    """Connecting line between two nodes, coloured by the left node's state."""
    color = _STAGE_COLORS[state]
    return (
        f'<div style="flex:1;height:3px;background:{color};margin-top:13.5px;'
        f'min-width:10px;border-radius:2px;'
        f'opacity:{"1" if state in ("done", "fail") else "0.55"};"></div>'
    )


def render_workflow_track(
    stages: List[Tuple[str, str]], legend: bool = True, subs: Optional[Dict[str, str]] = None
) -> None:
    """Draw the 7-stage path as circles + connecting lines (HTML, no deps).

    ``stages`` is ``[(label, state), ...]`` — state in done/active/pending/
    skip/fail. ``subs`` optionally maps a label to a small sub-caption
    (e.g. Photo → "attempt 2/3").
    """
    subs = subs or {}
    parts = ['<div style="display:flex;align-items:flex-start;gap:2px;margin:6px 0;">']
    for i, (label, state) in enumerate(stages):
        parts.append(_node_html(label, state, subs.get(label, "")))
        if i < len(stages) - 1:
            parts.append(_line_html(state))
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
    if legend:
        st.markdown(_STAGE_LEGEND, unsafe_allow_html=True)


def photo_sub_label(r: Dict[str, Any]) -> str:
    """``attempt 2/3`` under the Photo node when the photo gate is involved."""
    if not _needs_photo(r):
        return ""
    m = None
    for entry in r.get("decision_log") or []:
        match = re.search(r"attempt (\d+)/(\d+)", entry)
        if match:
            m = match
    return f"attempt {m.group(1)}/{m.group(2)}" if m else ""