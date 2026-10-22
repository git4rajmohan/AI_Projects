# Machine Monitoring page (spec1 §10 page 2; plan Phase 9): machine picker,
# latest values, configured limits, plotly trends, recent decisions, inspection
# history, on-demand decision analysis.

import json
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.settings import SENSOR_FRESHNESS_MINUTES
from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.maintenance_service import run_decision
from maintai.models import MachineLimits, SensorReading, validate_reading

st.set_page_config(page_title="Machine Monitoring — MaintAI", layout="wide",
                   page_icon="📊")
st.title("Machine Monitoring")

conn = get_conn()
init_db(conn)

machines = repo.list_machines(conn)
if not machines:
    st.warning("No machines registered. Run: `python -m maintai.seed`")
    st.stop()

machine_id = st.selectbox(
    "Machine", [m["machine_id"] for m in machines],
    format_func=lambda mid: f"{mid} — " + next(
        m["machine_name"] for m in machines if m["machine_id"] == mid))
machine = next(m for m in machines if m["machine_id"] == machine_id)
st.caption(f"Type: **{machine['machine_type'] or 'n/a'}** · Location: "
           f"**{machine['location'] or 'n/a'}** · Status: **{machine['status']}**")

limits_row = repo.active_limits(conn, machine_id)
if limits_row is None:
    st.error("No configured limits for this machine. Set them on the Machine "
             "Registry page.")
    st.stop()
limits = MachineLimits(**{k: limits_row[k] for k in repo.LIMIT_FIELDS})
st.markdown("#### Configured thresholds")
st.caption("Demonstration values — not universal limits for all machines.")
st.dataframe(pd.DataFrame([
    {"Channel": "Temperature (C)", "Warning": limits.temperature_warning,
     "Critical": limits.temperature_critical},
    {"Channel": "Vibration (mm/s)", "Warning": limits.vibration_warning,
     "Critical": limits.vibration_critical},
    {"Channel": "Motor load (%)", "Warning": limits.motor_load_warning,
     "Critical": limits.motor_load_critical},
]), hide_index=True, use_container_width=True)

history = repo.readings_window(conn, machine_id, limit=180)
if not history:
    st.warning("No sensor readings stored for this machine.")
    st.stop()

latest = history[-1]
age = (datetime.now() - datetime.fromisoformat(latest["timestamp"])).total_seconds() / 60
st.markdown("#### Latest readings")
st.caption(f"Reading of {latest['timestamp']} — {age:.0f} min ago "
           f"(freshness window: {SENSOR_FRESHNESS_MINUTES} min)")
labels = [("temperature_c", "Temp (C)"), ("vibration_mm_s", "Vib (mm/s)"),
          ("motor_load_percent", "Load (%)"), ("rpm", "RPM"),
          ("operating_hours", "Op hours")]
cols = st.columns(5)
for col, (field, label) in zip(cols, labels):
    value = latest[field]
    col.metric(label, "—" if value is None else f"{value:g}")

reading = SensorReading.model_validate({
    k: latest[k] for k in latest.keys() if k not in ("id", "validation_status")})
validation = validate_reading(reading, limits, SENSOR_FRESHNESS_MINUTES)
status_label = {"valid": "🟢 fresh & valid", "stale": "🟠 stale",
                "missing_data": "🟠 missing values", "invalid": "🔴 invalid"}
st.caption(f"Reading status: {status_label[validation.status]}"
           + ("" if validation.ok else f" — {'; '.join(validation.reasons)}"))

st.markdown("#### Sensor trends")
CHARTS = [("temperature_c", "Temperature (C)", "#d62728"),
          ("vibration_mm_s", "Vibration (mm/s)", "#1f77b4"),
          ("motor_load_percent", "Motor load (%)", "#2ca02c"),
          ("rpm", "Speed (rpm)", "#9467bd")]
for field, title, color in CHARTS:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[r["timestamp"] for r in history],
                             y=[r[field] for r in history], mode="lines",
                             line=dict(color=color)))
    fig.update_layout(title=title, height=260,
                      margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

st.markdown("#### Recent decisions")
decision_rows = repo.list_decisions(conn, machine_id, limit=5)
if decision_rows:
    st.dataframe(pd.DataFrame([
        {"Time": d["created_at"], "Outcome": d["policy_outcome"],
         "Alerts": (", ".join(json.loads(d["rule_alerts"]) or ["none"])
                    if d["rule_alerts"] else "n/a")}
        for d in decision_rows]), hide_index=True, use_container_width=True)
else:
    st.caption("No decisions recorded yet — run one below.")

st.markdown("#### Inspection history")
inspections = repo.list_inspections(conn, machine_id)
if inspections:
    st.dataframe(pd.DataFrame([{k: row[k] for k in ("inspection_date", "inspector",
                                                    "findings", "component_condition",
                                                    "action_taken", "resolution_status")}
                               for row in inspections]),
                  hide_index=True, use_container_width=True)
else:
    st.caption("No inspections recorded for this machine.")

st.markdown("#### Run a decision analysis")
st.caption("Validates the latest reading, applies engineering rules, consults "
           "Tev1, applies the deterministic policy — then stores the result.")
if st.button("Run decision analysis", type="primary"):
    with st.spinner("Running decision pipeline…"):
        try:
            record = run_decision(machine_id, conn)
        except ValueError as exc:
            st.error(str(exc))
        except sqlite3.Error:
            st.error("The database operation failed; no decision was saved. "
                     "Check that the database is available and writable, then retry.")
        else:
            out = record.outcome
            st.success(f"Decision recorded (id {record.decision_id}). "
                       f"Outcome: **{out.outcome}** → **{out.final_action}**")
            st.write(out.reason)
            if record.explanation:
                with st.expander("LLM explanation"):
                    st.write(record.explanation.get("summary"))
                    if record.explanation_error:
                        st.caption(f"({record.explanation_error} — a deterministic "
                                   "fallback was shown)")
            st.caption("Full breakdown on the Decision Workbench page.")