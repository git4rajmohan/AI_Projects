# Decision Workbench page (spec1 §10 page 3; plan Phase 9): full pipeline
# breakdown for one machine — model output panel clearly separated from the
# policy (application) decision, LLM explanation, review status.

import json
import sqlite3

import pandas as pd
import streamlit as st

from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.maintenance_service import run_decision

st.set_page_config(page_title="Decision Workbench — MaintAI", layout="wide",
                   page_icon="⚖️")
st.title("Decision Workbench")
st.caption("Every number shown is a value the model/pipeline actually returned — "
           "nothing fabricated.")

conn = get_conn()
init_db(conn)

machines = repo.list_machines(conn)
if not machines:
    st.warning("No machines registered. Run: `python -m maintai.seed`")
    st.stop()

machine_id = st.selectbox("Machine", [m["machine_id"] for m in machines])
col_run, col_show = st.columns([1, 3])
run = col_run.button("Run new decision analysis", type="primary")

# Latest persisted decision (auto-shown); a fresh run replaces it in session.
if run:
    with st.spinner("Validating → rules → Tev1 → policy → explanation…"):
        try:
            run_decision(machine_id, conn)
        except ValueError as exc:
            st.error(str(exc))
        except sqlite3.Error:
            st.error("The database operation failed; no decision was saved. "
                     "Check that the database is available and writable, then retry.")

decision = (repo.list_decisions(conn, machine_id, limit=1) or [None])[0]
if decision is None:
    st.info("No decision recorded for this machine yet. Run an analysis.")
    st.stop()

snapshot = json.loads(decision["input_snapshot"])
alerts = json.loads(decision["rule_alerts"])
explanation = json.loads(decision["llm_explanation"]) if decision["llm_explanation"] else None

st.markdown(f"#### Decision of {decision['created_at']} — machine `{machine_id}`")
if decision["error_status"]:
    st.error(f"Pipeline error status: `{decision['error_status']}`")

left, right = st.columns(2)

with left:  # ---- Model output (spec1 §10: clearly separated) ----
    with st.container(border=True):
        st.markdown("##### Model output (Tev1)")
        if decision["tev1_action"]:
            st.metric("Selected action", decision["tev1_action"])
            conf = decision["tev1_confidence"]
            st.metric("Confidence",
                      f"{conf * 100:.1f}%" if conf is not None else "not returned")
            probs = json.loads(decision["tev1_probabilities"]) \
                if decision["tev1_probabilities"] else {}
            if probs:
                st.markdown("**Probabilities**")
                for label, pct in sorted(probs.items(), key=lambda kv: -kv[1]):
                    st.progress(min(max(pct, 0.0), 1.0),
                                text=f"{label}  {pct * 100:5.1f}%")
            st.caption(f"Model: {decision['model_name']} · "
                       f"latency: {decision['latency_ms'] and round(decision['latency_ms'])} ms "
                       "(measured)")
        else:
            st.caption("No Tev1 output this run (see error status above).")

with right:  # ---- Application decision ----
    with st.container(border=True):
        st.markdown("##### Application decision (policy engine)")
        st.metric("Policy outcome", decision["policy_outcome"])
        review = ("review" in decision["policy_outcome"]
                  or "urgent" in decision["policy_outcome"]
                  or decision["tev1_action"] == "urgent_maintenance")
        st.metric("Human review required", "YES" if review else "no")
        st.caption(f"Policy version: **{decision['policy_version']}** "
                   "(limits version used for this decision)")

st.markdown("##### Validated input data")
st.dataframe(pd.DataFrame([{
    "Timestamp": snapshot.get("timestamp", ""),
    "Temperature (C)": snapshot.get("temperature_c"),
    "Vibration (mm/s)": snapshot.get("vibration_mm_s"),
    "Motor load (%)": snapshot.get("motor_load_percent"),
    "RPM": snapshot.get("rpm"),
}]), hide_index=True, use_container_width=True)

st.markdown("##### Engineering rule results")
if alerts:
    for alert in alerts:
        st.markdown(f"- ⚠️ {alert}")
else:
    st.markdown("- All sensor readings within configured limits.")

st.markdown("##### LLM explanation")
if explanation:
    st.write(explanation.get("summary"))
    col_e, col_c = st.columns(2)
    with col_e:
        st.markdown("**Evidence**")
        for item in explanation.get("evidence", []):
            st.markdown(f"- {item}")
    with col_c:
        st.markdown("**Recommended checks**")
        for item in explanation.get("recommended_checks", []):
            st.markdown(f"- {item}")
    if explanation.get("limitations"):
        st.caption("Limitations: " + " · ".join(explanation["limitations"]))
    if (decision["error_status"]
            and "llm_explanation_unavailable" in decision["error_status"]):
        st.caption("The LLM was unavailable — deterministic fallback explanation shown.")
else:
    st.caption("No explanation recorded for this decision.")

with st.expander("Technical details (raw input snapshot)"):
    st.json(snapshot)