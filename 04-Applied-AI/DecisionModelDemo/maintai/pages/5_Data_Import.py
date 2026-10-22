# Data Import page (spec1 §10 page 5 + §7 CSV upload; plan Phase 12):
# upload → preview → validation report → confirm-step insert, import history.
# Parsing/validation lives in maintai.import_core (pure, unit-tested).

from datetime import datetime
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.import_core import classify_rows, parse_csv

st.set_page_config(page_title="Data Import — MaintAI", layout="wide",
                   page_icon="📥")
st.title("Data Import")

conn = get_conn()
init_db(conn)

MACHINE_IDS = [m["machine_id"] for m in repo.list_machines(conn)]

# ---------------- sample downloads ----------------
data_dir = Path(__file__).resolve().parent.parent / "maintai" / "data"
sample_files = [
    ("Download sample CSV", "sample_sensor_readings.csv"),
    ("Download demo 1 — healthy", "demo_sample1_healthy.csv"),
    ("Download demo 2 — warning", "demo_sample2_warning.csv"),
    ("Download demo 3 — critical", "demo_sample3_critical.csv"),
]
for label, filename in sample_files:
    sample_path = data_dir / filename
    if sample_path.exists():
        st.download_button(label, data=sample_path.read_text(encoding="utf-8"),
                           file_name=filename, mime="text/csv")
st.caption("Demo files are ordered by timestamp. Import 1, then 2, then 3, "
           "and run decision analysis for BRG-001 after each import.")

# ---------------- import history ----------------
st.markdown("#### Import history")
history = [a for a in repo.list_audit(conn, limit=200)
           if a["event_type"] == "data_imported"]
if history:
    st.dataframe(pd.DataFrame([
        {"When": a["timestamp"], "By": a["user_id"] or "n/a",
         "File": a["entity_id"], "Details": a["details"]} for a in history]),
        hide_index=True, use_container_width=True)
else:
    st.caption("No imports recorded yet.")

# ---------------- upload + preview ----------------
st.markdown("#### Upload a CSV")
upload = st.file_uploader("Sensor readings CSV", type="csv")
if upload is None:
    st.stop()

filename = upload.name
try:
    rows = parse_csv(upload.getvalue().decode("utf-8-sig"))
except ValueError as exc:
    st.error(f"**Cannot import this file.** {exc}")
    st.stop()
except UnicodeDecodeError:
    st.error("Cannot read this file. Upload a CSV encoded as UTF-8.")
    st.stop()

report = classify_rows(rows, source_name=filename)
valid, quarantined = report["valid"], report["quarantined"]

st.markdown("##### Preview (first 5 rows)")
st.dataframe(pd.DataFrame(rows[:5]), hide_index=True, use_container_width=True)

# ---------------- validation report ----------------
st.markdown("##### Validation report")
ok_col, rej_col, dup_col, mach_col = st.columns(4)
ok_col.metric("Valid rows", len(valid))
rej_col.metric("Rejected rows", len(quarantined))
dup_col.metric("In-file duplicate timestamps", len(report["in_file_dupes"]))
mach_col.metric("Machines covered", len(report["machine_ids"]))

already = 0  # rows whose (machine_id, timestamp) already exist in the db
if valid:
    unknown = [m for m in report["machine_ids"] if m not in MACHINE_IDS]
    if unknown:
        st.warning("Unknown machine id(s) — register them on the Machine "
                   "Registry page first: " + ", ".join(unknown))
    for m in report["machine_ids"]:
        for v in (v for v in valid if v["machine_id"] == m):
            if repo.active_limits(conn, m) is None:
                st.warning(f"Machine {m} has no configured thresholds; "
                           "decisions will need Registry setup.")
                break
    keys = {(v["machine_id"], v["timestamp"].isoformat(sep=" "))
            for v in valid}
    if MACHINE_IDS:
        ph = ",".join("?" * len(MACHINE_IDS))
        in_db = {(r["machine_id"], r["timestamp"]) for r in conn.execute(
            f"SELECT machine_id, timestamp FROM sensor_readings "
            f"WHERE machine_id IN ({ph})", MACHINE_IDS)}
        already = len(keys & in_db)
        if already:
            st.info(f"{already} row(s) already exist in the database — they "
                    "will be skipped on import (INSERT OR IGNORE).")

if quarantined:
    st.markdown("##### Rejected rows (quarantined — not imported)")
    st.dataframe(pd.DataFrame([
        {"Line": i + 2, "Machine": q[0].get("machine_id"),
         "Timestamp": q[0].get("timestamp"), "Reason": q[1]}
        for i, q in enumerate(quarantined)]),
        hide_index=True, use_container_width=True)

# ---------------- confirm import ----------------
st.markdown("#### Confirm import")
st.caption(f"Will insert {len(valid)} valid rows ({already} duplicates in db "
           "skipped automatically). data_source is set to the filename.")
confirm = st.button("Confirm import", type="primary", disabled=not valid,
                    help="Writes the valid rows and records the import in the "
                         "audit log.")
if confirm:
    try:
        with conn:
            for v in valid:
                repo.insert_reading(conn, v, validation_status=v["validation_status"])
            repo.record_audit(conn, "dashboard", "data_imported", "machine", filename,
                              {"valid": len(valid), "rejected": len(quarantined),
                               "in_file_dupes": len(report["in_file_dupes"]),
                               "already_in_db": already,
                               "machines": report["machine_ids"]})
    except sqlite3.Error:
        st.error("Import failed while saving to the database. No rows were imported; "
                 "check database availability and retry.")
    else:
        st.success(f"Imported {len(valid)} row(s) from **{filename}** "
                   f"({len(quarantined)} rejected, {len(report['in_file_dupes'])} "
                   f"in-file duplicates, {already} db duplicates skipped).")
        st.toast(f"Imported {len(valid)} row(s) from {filename} — history updated.")