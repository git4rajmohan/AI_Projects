# Executive Dashboard page (spec1 §10 page 1; plan Phase 10): fleet KPIs,
# plotly alert trend + actions-by-category, synthetic-data banner. KPI counts
# come straight from the repository aggregates so the page shows db truth.

import pandas as pd
import plotly.express as px
import streamlit as st

from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db

st.set_page_config(page_title="Executive Dashboard — MaintAI", layout="wide",
                   page_icon="🏭")
st.title("Executive Dashboard")
st.caption("Counts reflect the database as of page load. Alerts include "
           "historical decisions — an alert stays visible here even after a "
           "review is recorded; the live 'requiring review' count below "
           "excludes machines with a recorded inspection outcome.")

conn = get_conn()
init_db(conn)

machines = repo.list_machines(conn)
totals = repo.dashboard_kpis(conn)
if not machines:
    st.warning("No machines registered. Run: `python -m maintai.seed`")
    st.stop()

kpi_labels = [
    ("Registered machines", totals["registered_machines"]),
    ("Machines requiring review (live)", totals["machines_requiring_review"]),
    ("High-priority alerts, 7d", totals["active_high_priority_alerts"]),
    ("Pending inspections", totals["pending_inspections"]),
    ("Decisions, 7d", totals["recent_decisions"]),
]
cols = st.columns(len(kpi_labels))
for col, (label, value) in zip(cols, kpi_labels):
    col.metric(label, value)

st.info(
    "🧪 **Synthetic demonstration data.** Simulated readings, demonstration "
    "thresholds — no outcome predicts actual failures.", icon="⚠️")

left, right = st.columns(2)

with left:  # alert trend by day
    days = repo.alerts_over_time(conn, since_days=7)
    st.markdown("##### Alert-worthy decisions per day (7d)")
    if days:
        fig = px.bar(pd.DataFrame([{"Day": str(d["day"]), "Alerts": d["alerts"]}
                                   for d in days]),
                     x="Day", y="Alerts")
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No alert-worthy decisions in the last 7 days.")

with right:  # policy outcomes by category
    counts = repo.action_counts(conn, since_days=7)
    st.markdown("##### Policy outcomes by category (7d)")
    if counts:
        fig = px.pie(pd.DataFrame([{"Outcome": c[0], "Decisions": c[1]}
                                   for c in counts]),
                     names="Outcome", values="Decisions", hole=0.45)
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320,
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No decisions in the last 7 days.")

st.markdown("##### Machine action flags")
st.caption("Based on each machine's latest decision. Red means review/action "
           "is pending; yellow means inspect or observe; green means an "
           "accepted monitor decision. Gray means not yet assessed.")
machine_statuses = repo.machine_action_statuses(conn)
st.dataframe(pd.DataFrame([{
    "Machine": f"{m['machine_id']} — {m['machine_name']}",
    "Flag": f"{m['flag']} {m['status']}",
    "Latest TEV1 action": m["tev1_action"] or "—",
    "Policy outcome": m["policy_outcome"] or "—",
    "Assessed": m["created_at"] or "Never",
} for m in machine_statuses]), hide_index=True, use_container_width=True)

st.markdown("##### Recent decisions (all machines, historical)")
decision_rows = repo.list_decisions(conn, limit=10)
if decision_rows:
    st.dataframe(pd.DataFrame([
        {"Time": d["created_at"], "Machine": d["machine_id"],
         "Tev1": d["tev1_action"] or "—",
         "Outcome": d["policy_outcome"], "Error": d["error_status"] or ""}
        for d in decision_rows]), hide_index=True, use_container_width=True)
else:
    st.caption("No decisions recorded yet — run one from Machine Monitoring.")