# Workflow page — read-only view of the project plan status (plan.md Phase 0-12).
# Additive page: no API calls, no session-state coupling — safe to visit any time.
import streamlit as st

st.set_page_config(page_title="Workflow — Decision + LLM Playground", layout="wide")
st.title("Workflow & Progress")
st.caption("Project plan (plan.md) phases 0–12 with activity status. No model calls on this page.")

COMPLETED = "🟢 Completed"

PHASES = [
    ("Phase 0", "Workspace Bootstrap", ".venv (Python 3.11.9), .env structure, .env.example placeholders, .gitignore", "2026-10-02"),
    ("Phase 1", "Dependencies + Config", "requirements.txt pinned; config/settings.py via load_dotenv(); validate_settings() / is_configured()", "2026-10-02"),
    ("Phase 2", "Tev1 Decision Service", "Live probe of undocumented /v1/systemone contract; typed errors, timed calls, self-test block", "2026-10-02"),
    ("Phase 3", "Ollama Cloud LLM Service", "Bearer auth, 401/404/timeout friendly messages, real token counts, key never echoed", "2026-10-02"),
    ("Phase 4", "Result Processor", "Common display objects, sorted probability list, comparison payload, pure functions", "2026-10-02"),
    ("Phase 5", "Prompt Templates", "Per-mode DECISION / EXPLANATION / COMBINED templates + builders + autofill_criteria contract fix", "2026-10-02"),
    ("Phase 6", "Streamlit App Skeleton", "Sidebar config + cached status pills, input section, hero empty state", "2026-10-02"),
    ("Phase 7", "Execution Modes", "LLM Only / Tev1 + LLM / Compare Both wiring; session-state results; result panels", "2026-10-02"),
    ("Phase 8", "Demo Modes + Custom", "Mode presets, Customer Support / QA / General templates; Custom decision mode validated pre-API", "2026-10-02"),
    ("Phase 9", "Evaluation Feature", "Scoring core; batch run, metrics, capture flow, CSV exports under evaluation/exports/", "2026-10-02"),
    ("Phase 10", "Error Handling + Security", "All 10 friendly-error cases; API-key audit clean (key only in settings loading + request header)", "2026-10-02"),
    ("Phase 11", "Automated Tests", "6 test files, HTTP mocked; 32 passed / 2 skipped offline; live smoke gated by RUN_LIVE_TESTS=1", "2026-10-02"),
    ("Phase 12", "README + Demo Rehearsal", "README with 5-min demo; live model-swap rehearsal (zero code changes); acceptance sweep", "2026-10-02"),
]

# Post-sign-off follow-ups verified live today (kept so the page reflects reality).
FIXES = [
    ("2026-10-19", "Evaluation page crash (tuple assigned where rows expected)",
     "Unpacked (rows, corrupt_msg) from load_scenarios_safe() + render corrupt-file message; pytest 32/32 green."),
    ("2026-10-19", "Tev1 HTTP 400: 'tev1:4b' was downloaded in a format that is no longer supported",
     "Re-downloaded via ollama pull tev1:4b. Self-test duplicate_charge 99.66%; batch 6/6 rows OK, 94.0% avg confidence."),
]

OUT_OF_SCOPE = (
    "RAG integration · multiple decision models · evaluation dashboard · A/B testing · "
    "prompt comparison · confidence-threshold UI · human-in-the-loop approval · "
    "JSON export beyond eval CSV · decision history · cost/latency dashboards · automated browser tests."
)

# --- Status summary -----------------------------------------------------------
cols = st.columns(3)
cols[0].metric("Completed", f"🟢 {len(PHASES)} / {len(PHASES)} phases")
cols[1].metric("In progress", "🟡 0")
cols[2].metric("Not started", "⚪ 0", help="Out-of-scope items (spec §28) are future work by design, listed at the bottom.")

# --- Flow chain (text-based, no extra dependencies) ---------------------------
chain = "  →  ".join(f"**{p[0].replace('Phase ', 'P')}**" for p in PHASES)
st.markdown(f"### Flow\n{chain}")
st.caption(
    "Branches: after P1 the Tev1 service (P2→P4) and cloud LLM service (P3→P5) run in parallel "
    "and merge at the app skeleton (P6), then proceed linearly to sign-off (P12). All nodes completed + live-verified."
)

# --- Phase table with expandable activity detail ------------------------------
st.markdown("### Phases")
for name, title, activities, verified in PHASES:
    with st.expander(f"{COMPLETED} — {name} · {title}"):
        st.markdown(f"**Activities:** {activities}")
        st.markdown(f"**Verified live:** {verified}")

# --- Post-sign-off fixes -------------------------------------------------------
st.markdown("### Post-sign-off fixes")
for date, issue, fix in FIXES:
    with st.expander(f"🟢 {date} — {issue}"):
        st.markdown(f"**Fix:** {fix}")

# --- Out of scope ---------------------------------------------------------------
st.markdown("### Out of scope (spec §28) — not started, by design")
st.info(f"⚪ {OUT_OF_SCOPE}")