# Settings page (spec1 §10 page 8; plan Phase 14): show the live .env-derived
# configuration (key NAMES only — API-key values are never shown), run
# connection checks with actionable fixes, session-scoped overrides.

import pandas as pd
import requests
import streamlit as st

from config.settings import (LLM_BASE_URL, LLM_MODEL, OLLAMA_HOST,
                             SENSOR_FRESHNESS_MINUTES,
                             TEV1_CONFIDENCE_REVIEW_THRESHOLD, TEV1_MODEL,
                             TREND_WINDOW_READINGS)
from maintai.database.connection import get_conn
from maintai.database import repository as repo

st.set_page_config(page_title="Settings — MaintAI", layout="wide",
                   page_icon="⚙️")
st.title("Settings")

conn = get_conn()

# ---------------- current configuration ----------------
st.markdown("#### Current configuration (from .env via config/settings.py)")
st.dataframe(pd.DataFrame([
    ("OLLAMA_HOST (local Ollama / Tev1)", OLLAMA_HOST),
    ("TEV1_MODEL (decision model)", TEV1_MODEL),
    ("LLM_BASE_URL (generative LLM)", LLM_BASE_URL),
    ("LLM_MODEL (generative LLM)", LLM_MODEL or "(empty)"),
    ("OLLAMA_API_KEY", "(value never displayed — spec §15/§25)"),
    ("OLLAMA_CLOUD_API_KEY .env name", "OLLAMA_API_KEY"),
    ("TEV1_CONFIDENCE_REVIEW_THRESHOLD", TEV1_CONFIDENCE_REVIEW_THRESHOLD),
    ("SENSOR_FRESHNESS_MINUTES", SENSOR_FRESHNESS_MINUTES),
    ("TREND_WINDOW_READINGS", TREND_WINDOW_READINGS),
], columns=["Setting (.env key)", "Value"]), hide_index=True,
    use_container_width=True)
st.caption("LLM timeouts live in TEV1_TIMEOUT_SECONDS / LLM_TIMEOUT_SECONDS; "
           "ROC tuning keys: TEMPERATURE_ROC_C_PER_H, VIBRATION_ROC_MM_S_PER_H, "
           "MOTOR_LOAD_ROC_PCT_PER_H. All persist via .env only — no runtime "
           ".env writes.")

# ---------------- connection checks ----------------
st.markdown("#### Connection checks")

def check(label: str, ok: bool, fix: str):
    if ok:
        st.markdown(f"🟢 **{label}**")
    else:
        st.markdown(f"🔴 **{label}** — fix: {fix}")

local_ok = cloud_ok = False
tev1_ok = llm_ok = None
try:
    local_ok = requests.get(f"{OLLAMA_HOST}/api/version", timeout=3).ok
except requests.exceptions.RequestException:
    pass
check(f"Local Ollama at {OLLAMA_HOST}", local_ok,
      "Start Ollama (or fix OLLAMA_HOST in .env), then reload this page.")

if local_ok:
    try:
        tags = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3).json()
        names = [m.get("name", "") for m in tags.get("models", [])]
        tev1_ok = any(n == TEV1_MODEL or n.split(":")[0] == TEV1_MODEL
                      for n in names)
        check(f"Tev1 model '{TEV1_MODEL}' present on local Ollama", tev1_ok,
              f"Run: ollama pull {TEV1_MODEL}")
    except (requests.exceptions.RequestException, ValueError):
        st.markdown(f"🔴 **Tev1 model list failed** — fix: verify Ollama at "
                    f"{OLLAMA_HOST} (GET /api/tags).")
else:
    st.markdown(f"⚪ **Tev1 model check skipped** — local Ollama is not "
                f"reachable (run: `ollama pull {TEV1_MODEL}`).")

try:
    resp = requests.get(LLM_BASE_URL, timeout=4)
    cloud_ok = resp.status_code < 500
    check(f"LLM host reachable at {LLM_BASE_URL}", cloud_ok,
          "Check your network or fix LLM_BASE_URL in .env, then reload.")
except requests.exceptions.RequestException:
    check(f"LLM host reachable at {LLM_BASE_URL}", False,
          "Check your network or fix LLM_BASE_URL in .env, then reload.")
if cloud_ok:
    llm_ok = bool(LLM_MODEL)
    check(f"LLM model '{LLM_MODEL}' configured", llm_ok,
          "Set LLM_MODEL in .env (e.g. glm-5.3-flash:cloud), then reload.")

# ---------------- session overrides ----------------
st.markdown("#### Session overrides (this browser tab only)")
st.caption("Used by the next decision runs on Monitoring / Workbench. Values "
           "reset when the session ends — persist via .env for a permanent "
           "change. The threshold applies on the next workbench/monitoring "
           "run (config/settings values are read fresh per decision).")

with st.form("overrides_form"):
    col1, col2 = st.columns(2)
    conf_override = col1.number_input(
        "TEV1_CONFIDENCE_REVIEW_THRESHOLD", 0.0, 1.0,
        value=float(st.session_state.get("override_confidence_threshold",
                                         TEV1_CONFIDENCE_REVIEW_THRESHOLD)),
        step=0.05,
        help="Below this the policy requires human review (policy rung 5).")
    fresh_override = col2.number_input(
        "SENSOR_FRESHNESS_MINUTES", 5, 20_000,
        value=int(st.session_state.get("override_freshness_minutes",
                                       SENSOR_FRESHNESS_MINUTES)),
        step=5,
        help="Readings older than this are validated as 'stale'.")
    col_clear, _ = st.columns([1, 3])
    submitted = st.form_submit_button("Apply overrides (session)")
    cleared = st.form_submit_button("Reset to .env defaults")

if cleared:
    st.session_state.pop("override_confidence_threshold", None)
    st.session_state.pop("override_freshness_minutes", None)
    st.success("Overrides cleared — .env defaults apply again.")
if submitted:
    st.session_state["override_confidence_threshold"] = float(conf_override)
    st.session_state["override_freshness_minutes"] = int(fresh_override)
    st.success(f"Session overrides applied: confidence ≥ "
               f"{conf_override:g}, freshness {int(fresh_override)} min. "
               f"Next decision runs use them; persist via .env to keep.")

active_conf = st.session_state.get("override_confidence_threshold",
                                   TEV1_CONFIDENCE_REVIEW_THRESHOLD)
active_fresh = st.session_state.get("override_freshness_minutes",
                                    SENSOR_FRESHNESS_MINUTES)
st.caption(f"Active this session: confidence ≥ {active_conf:g} · freshness "
           f"{active_fresh:g} min ({'session override' if 'override_confidence_threshold' in st.session_state or 'override_freshness_minutes' in st.session_state else '.env values'})")