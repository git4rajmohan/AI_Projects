# Maintenance History page (spec1 §10 page 6; plan Phase 10): decision history
# filtered by machine, "Record inspection outcome" form → inspections + audit
# row carrying decision_id (which removes the machine from the dashboard's
# live "requiring review" KPI — the closed loop).

import json
import sqlite3

import pandas as pd
import streamlit as st

from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.maintenance_service import record_inspection

ROLES = ["Viewer", "Engineer", "Administrator"]


def reviewed_decision_ids(audit_rows):
    """Decision ids closed out by a recorded inspection (audit details JSON)."""
    ids = set()
    for a in audit_rows:
        if a["event_type"] != "inspection_recorded" or not a["details"]:
            continue
        try:
            details = json.loads(a["details"])
        except (TypeError, ValueError):
            continue
        if (isinstance(details, dict)
                and details.get("resolution_status", "closed") == "closed"
                and details.get("decision_id")):
            ids.add(details["decision_id"])
    return ids

st.set_page_config(page_title="Maintenance History — MaintAI", layout="wide",
                   page_icon="🧾")
st.title("Maintenance History")

with st.sidebar:
    role = st.selectbox("Role (demo)", ROLES, index=1, key="maintai_role")

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
decisions = repo.list_decisions(conn, machine_id, limit=50)

# ---------------- decision history ----------------
st.markdown("#### Decision history")
if not decisions:
    st.caption("No decisions recorded for this machine. Run one from Machine "
               "Monitoring.")
else:
    reviewed_ids = reviewed_decision_ids(
        repo.list_audit(conn, entity_id=machine_id, limit=500))
    st.dataframe(pd.DataFrame([
        {"Id": d["id"], "Time": d["created_at"],
         "Tev1 action": d["tev1_action"] or "—",
         "Outcome": d["policy_outcome"],
         "Alerts": (", ".join(json.loads(d["rule_alerts"]) or ["none"])
                    if d["rule_alerts"] else "n/a"),
         "Error": d["error_status"] or "",
         "Review status": ("Reviewed" if d["id"] in reviewed_ids
                           else "Pending" if (
                               "review" in (d["policy_outcome"] or "")
                               or "urgent" in (d["policy_outcome"] or "")
                               or d["tev1_action"] == "urgent_maintenance")
                           else "Not required")}
        for d in decisions]), hide_index=True, use_container_width=True)

# ---------------- record inspection outcome ----------------
st.markdown("#### Record inspection outcome")
st.caption("Links the inspection to a decision and clears that machine's "
           "live 'requiring review' status on the dashboard.")
if not decisions:
    st.info("Nothing to close out — record a decision first.")
    st.stop()

if role == "Viewer":
    st.info("Recording a review requires the Engineer or Administrator role.")

with st.form("inspection_form", clear_on_submit=True):
    decision_id = st.selectbox(
        "Decision being closed out",
        [d["id"] for d in decisions],
        format_func=lambda did: f"#{did} — " + next(
            (d["policy_outcome"] for d in decisions
             if d["id"] == did), "?"))
    col1, col2 = st.columns(2)
    inspector = col1.text_input("Inspector")
    inspection_date = col2.date_input("Inspection date")
    findings = st.text_area("Findings")
    component_condition = col1.text_input("Component condition")
    action_taken = col2.text_input("Action taken")
    resolution_status = st.selectbox(
        "Resolution status", ["open", "closed"],
        index=0 if any(
            "review" in (d["policy_outcome"] or "")
            or "urgent" in (d["policy_outcome"] or "")
            or d["tev1_action"] == "urgent_maintenance"
            for d in decisions) else 1)
    submitted = st.form_submit_button("Record inspection", type="primary",
                                     disabled=role == "Viewer")

if submitted:
    missing = [f for f, v in (("Inspector", inspector), ("Findings", findings))
               if not v.strip()]
    if missing:
        st.error("Required: " + ", ".join(missing))
    elif role not in ("Engineer", "Administrator"):
        st.error("Engineer or Administrator role is required to record a review.")
    else:
        try:
            cur = record_inspection(conn, machine_id, decision_id, dict(
                inspection_date=inspection_date.isoformat(),
                inspector=inspector, findings=findings,
                component_condition=component_condition.strip(),
                action_taken=action_taken.strip(),
                resolution_status=resolution_status), role)
        except sqlite3.Error:
            st.error("Could not save the inspection. Check database availability "
                     "and try again; no review was recorded.")
        except (ValueError, PermissionError) as exc:
            st.error(str(exc))
        else:
            st.success(f"Inspection #{cur} recorded for decision #{decision_id}. "
                       "Reviewer and timestamp are in the audit history.")

# ---------------- inspection history ----------------
st.markdown("#### Inspection history")
inspections = repo.list_inspections(conn, machine_id)
if inspections:
    st.dataframe(pd.DataFrame([
        {"Id": r["id"], "Date": r["inspection_date"], "Inspector": r["inspector"],
         "Findings": r["findings"], "Condition": r["component_condition"],
         "Action taken": r["action_taken"],
         "Status": r["resolution_status"]}
        for r in inspections]), hide_index=True, use_container_width=True)
else:
    st.caption("No inspections recorded for this machine.")