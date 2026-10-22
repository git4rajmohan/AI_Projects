# Machine Registry page (spec1 §10 page 4 + §15; plan Phase 11): add/edit
# machines, versioned threshold edits (append-only limit versions), machine
# escalation flag, configuration history. Role demo governs who can write:
# Viewer read-only; Engineer+ may change; Administrator bypasses confirmation.

import datetime as dt

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.models import MachineLimits

ROLES = ["Viewer", "Engineer", "Administrator"]  # spec1 §15 demo roles

st.set_page_config(page_title="Machine Registry — MaintAI", layout="wide",
                   page_icon="🔧")
st.title("Machine Registry")

conn = get_conn()
init_db(conn)

with st.sidebar:  # session role selector (prototype auth, spec1 §15)
    role = st.selectbox("Role (demo)", ROLES, index=1, key="maintai_role")
can_edit = role in ("Engineer", "Administrator")

machines = repo.list_machines(conn)
if not machines:
    st.warning("No machines registered. Run: `python -m maintai.seed` or add "
               "one below.")
    st.stop()

machine_id = st.selectbox(
    "Machine", [m["machine_id"] for m in machines],
    format_func=lambda mid: f"{mid} — " + next(
        m["machine_name"] for m in machines if m["machine_id"] == mid))
machine = next(m for m in machines if m["machine_id"] == machine_id)


def audit(user, event, entity, details):
    repo.record_audit(conn, user, event, "machine", entity, details)
    conn.commit()


def save_machine(machine_id, fields):
    """Single write path for machine details, audited with the role."""
    row = repo.get_machine(conn, machine_id)
    if row is None:
        raise ValueError(f"Machine '{machine_id}' not found.")
    repo.upsert_machine(conn, {
        "machine_id": machine_id, "machine_name": row["machine_name"],
        "machine_type": row["machine_type"], "location": row["location"],
        "team": row["team"], "status": row["status"], **fields})
    audit(role, "machine_updated", machine_id, fields)


def save_limits(machine_id, values):
    """Append a new limit version (old one stays for as-of reproduction)."""
    version = repo.insert_limit_version(conn, machine_id, values, dt.datetime.now())
    audit(role, "thresholds_updated", machine_id, {"version": version, **values})
    return version


# ---------------- machine details ----------------
st.markdown("#### Machine details")
with st.form("machine_form"):
    col1, col2 = st.columns(2)
    name = col1.text_input("Machine name", value=machine["machine_name"],
                           disabled=not can_edit)
    mtype = col2.text_input("Machine type", value=machine["machine_type"],
                            disabled=not can_edit)
    location = col1.text_input("Location", value=machine["location"],
                               disabled=not can_edit)
    team = col2.text_input("Maintenance team", value=machine["team"],
                           disabled=not can_edit)
    escalation = st.selectbox(
        "Machine-level escalation flag",
        ["active", "mandatory_escalation"],
        index=0 if machine["status"] != "mandatory_escalation" else 1,
        help="Machines with mandatory escalation always get urgent human review "
             "(policy rung 2) regardless of model output.",
        disabled=not can_edit)
    details_submitted = st.form_submit_button(
        "Save machine details", disabled=not can_edit)

if details_submitted:
    save_machine(machine_id, {"machine_name": name.strip(),
                              "machine_type": mtype.strip(),
                              "location": location.strip(),
                              "team": team.strip(), "status": escalation})
    st.success("Machine details saved and audited.")

# ---------------- threshold configuration ----------------
st.markdown("#### Sensor threshold configuration")
st.caption("Demonstration values — not universal limits for all machines. An "
           "edit writes a NEW version; decisions reproduce with as-of limits.")
limits_row = repo.active_limits(conn, machine_id)
limits = MachineLimits(**{k: limits_row[k] for k in repo.LIMIT_FIELDS})
with st.form("limits_form"):
    col1, col2 = st.columns(2)
    t_warn = col1.number_input("Temperature warning (C)", value=limits.temperature_warning,
                               disabled=not can_edit)
    t_crit = col2.number_input("Temperature critical (C)", value=limits.temperature_critical,
                               disabled=not can_edit)
    v_warn = col1.number_input("Vibration warning (mm/s)", value=limits.vibration_warning,
                               disabled=not can_edit)
    v_crit = col2.number_input("Vibration critical (mm/s)", value=limits.vibration_critical,
                               disabled=not can_edit)
    l_warn = col1.number_input("Motor load warning (%)", value=limits.motor_load_warning,
                               disabled=not can_edit)
    l_crit = col2.number_input("Motor load critical (%)", value=limits.motor_load_critical,
                               disabled=not can_edit)
    confirm_text = st.text_input(
        f"Type the machine id to confirm threshold changes ({machine_id})",
        disabled=not can_edit or role == "Administrator")
    limits_submitted = st.form_submit_button(
        "Save as new version", disabled=not can_edit)

def parse_limits():
    """Build MachineLimits from the form; returns (limits, error-message)."""
    try:
        return MachineLimits(
            temperature_warning=t_warn, temperature_critical=t_crit,
            vibration_warning=v_warn, vibration_critical=v_crit,
            motor_load_warning=l_warn, motor_load_critical=l_crit), None
    except ValidationError as exc:
        return None, exc.errors()[0]["msg"]  # e.g. warning must be below critical


if limits_submitted:
    if confirm_text.strip() != machine_id:
        st.error("Typed confirmation does not match the machine id — thresholds "
                 "not changed.")
    else:
        new, err = parse_limits()
        if err:
            st.error(err)
        else:
            version = save_limits(machine_id, new.model_dump())
            st.success(f"Thresholds saved as version {version}; decision "
                       "history stays reproducible with as-of limits.")
st.caption(f"Current policy version: **v{limits_row['version']}**")

# ---------------- configuration history ----------------
st.markdown("#### Configuration history")
versions = repo.list_limit_versions(conn, machine_id)
st.dataframe(pd.DataFrame([
    {"Version": v["version"],
     "Effective from": v["effective_from"],
     "Effective to": v["effective_to"] or "current",
     "Temp warn/crit": f"{v['temperature_warning']}/{v['temperature_critical']}",
     "Vib warn/crit": f"{v['vibration_warning']}/{v['vibration_critical']}",
     "Load warn/crit": f"{v['motor_load_warning']}/{v['motor_load_critical']}"}
    for v in versions]), hide_index=True, use_container_width=True)

changes = [a for a in repo.list_audit(conn, entity_id=machine_id, limit=100)
           if a["event_type"] in ("machine_updated", "thresholds_updated")]
if changes:
    st.dataframe(pd.DataFrame([
        {"When": a["timestamp"], "Who": a["user_id"] or "n/a", "Change": a["event_type"],
         "Details": a["details"]} for a in changes]),
        hide_index=True, use_container_width=True)
else:
    st.caption("No recorded configuration changes for this machine.")

# ---------------- add a machine ----------------
st.markdown("#### Add a machine")
if not can_edit:
    st.caption(f"Role '{role}' is read-only — switch to Engineer or "
               "Administrator (sidebar) to add machines.")
with st.form("add_machine_form"):
    col1, col2 = st.columns(2)
    new_id = col1.text_input("Machine id (e.g. PMP-002)")
    new_name = col2.text_input("Machine name")
    new_type = col1.text_input("Type")
    new_location = col2.text_input("Location")
    new_team = col1.text_input("Team")
    new_status = col2.selectbox("Escalation flag", ["active", "mandatory_escalation"])
    add_submitted = st.form_submit_button("Add machine")

if add_submitted and can_edit:
    if new_id.strip() == "" or new_name.strip() == "":
        st.error("Machine id and name are required.")
    elif repo.get_machine(conn, new_id.strip()) is not None:
        st.error(f"Machine '{new_id.strip()}' already exists.")
    else:
        repo.upsert_machine(conn, {
            "machine_id": new_id.strip(), "machine_name": new_name.strip(),
            "machine_type": new_type.strip(), "location": new_location.strip(),
            "team": new_team.strip(), "status": new_status})
        limits = MachineLimits().model_dump()  # demonstration defaults to start
        repo.insert_limit_version(conn, new_id.strip(), limits, dt.datetime.now())
        audit(role, "machine_added", new_id.strip(),
              {"team": new_team.strip(), "status": new_status})
        st.success(f"Machine '{new_id.strip()}' registered with default "
                   "demonstration thresholds (v1). Adjust them above.")