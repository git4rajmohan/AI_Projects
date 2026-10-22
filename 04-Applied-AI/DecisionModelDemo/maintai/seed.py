# Seed script (plan Phase 3): db init, 5 demo machines, 10 days of hourly
# synthetic readings, sample CSVs, a few inspection + audit rows.
# Run: .venv\Scripts\python.exe -m maintai.seed   (from the repo root)

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import ENABLE_SYNTHETIC_DATA
from maintai.database.connection import get_conn, init_db
from maintai.database import repository as repo
from maintai.models import MachineLimits

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "maintai" / "data"
HOURS = 10 * 24  # ten days, hourly

# Per-machine scenario: baseline levels + drift/excursion behaviour.
# Limits are DEMONSTRATION values per machine, not universal specs (spec1 §6.1).
MACHINES = [
    dict(machine_id="BRG-001", machine_name="Bearing test rig A",
         machine_type="Bearing test rig", location="Bay 1",
         team="Rotating equipment",
         scenario="degrading",          # gradual deterioration
         limits=MachineLimits().model_dump()),
    dict(machine_id="MIX-001", machine_name="Mixer line 2",
         machine_type="Industrial mixer", location="Bay 3",
         team="Process line",
         scenario="normal",             # healthy the whole window
         limits=MachineLimits(temperature_warning=70, temperature_critical=85,
                              vibration_warning=3.0, vibration_critical=4.0,
                              motor_load_warning=70, motor_load_critical=80).model_dump()),
    dict(machine_id="PMP-001", machine_name="Coolant pump B",
         machine_type="Centrifugal pump", location="Utility room",
         team="Fluids team",
         scenario="critical",           # spike over critical at the end
         limits=MachineLimits().model_dump()),
    dict(machine_id="MTR-001", machine_name="Conveyor motor C",
         machine_type="Electric motor", location="Line 4",
         team="Conveying",
         scenario="missing",            # dropouts + one stale-looking gap
         limits=MachineLimits().model_dump()),
    dict(machine_id="CPR-001", machine_name="Compressor D",
         machine_type="Reciprocating compressor", location="Bay 5",
         team="Fluids team",
         scenario="excursion",          # single sudden sensor excursion
         limits=MachineLimits().model_dump()),
]

BASE = dict(  # healthy operating point (per-machine noise added below)
    temperature_c=68.0, vibration_mm_s=2.4, motor_load_percent=72.0,
    rpm=1780.0, operating_hours=0.0,
)


def _scenario_values(scenario, hour, rnd):
    """Synthetic sensor point for one hour index. Clearly artificial shapes."""
    base = dict(BASE)
    if scenario == "degrading":
        frac = hour / HOURS
        base["temperature_c"] += 25 * frac ** 2          # creep past warning
        base["vibration_mm_s"] += 2.5 * frac ** 2        # and vibration
        base["motor_load_percent"] += 15 * frac
    elif scenario == "critical" and hour >= HOURS - 6:
        base.update(temperature_c=96.0, vibration_mm_s=6.4, motor_load_percent=92.0)
    elif scenario == "excursion" and hour == HOURS - 12:
        base.update(temperature_c=91.0, vibration_mm_s=5.2)
    base["temperature_c"] += rnd.uniform(-1.0, 1.0)
    base["vibration_mm_s"] += rnd.uniform(-0.2, 0.2)
    base["motor_load_percent"] += rnd.uniform(-2.0, 2.0)
    base["rpm"] += rnd.uniform(-15, 15)
    return base


def generate_readings(machine: dict, start: datetime, rnd):
    rows = []
    for hour in range(HOURS):
        ts = start + timedelta(hours=hour)
        values = _scenario_values(machine["scenario"], hour, rnd)
        values["operating_hours"] = 1000.0 + hour
        if machine["scenario"] == "missing" and hour % 29 == 0:
            values["vibration_mm_s"] = None            # dropouts, never zero
        if machine["scenario"] == "missing" and hour % 53 == 0:
            values["temperature_c"] = None
        rows.append({"machine_id": machine["machine_id"], "timestamp": ts,
                     **values, "data_source": "synthetic (demo)"})
    return rows


def seed(force: bool = False) -> dict:
    if not (ENABLE_SYNTHETIC_DATA or force):
        raise RuntimeError(
            "ENABLE_SYNTHETIC_DATA is false in .env. Set it to true "
            "(or run with --force) to generate demonstration data."
        )
    conn = get_conn()
    init_db(conn)
    existing = {r["machine_id"] for r in repo.list_machines(conn)}
    start = (datetime.now().replace(minute=0, second=0, microsecond=0)
             - timedelta(hours=HOURS))
    counts = {}

    all_rows = []
    for machine in MACHINES:
        rnd = random.Random(42 + MACHINES.index(machine))  # fixed seed: reproducible
        if machine["machine_id"] in existing:
            continue  # idempotent: re-running never duplicates
        repo.upsert_machine(conn, machine)
        repo.insert_limit_version(conn, machine["machine_id"],
                                  machine["limits"], datetime.now())
        rows = generate_readings(machine, start, rnd)
        all_rows += rows
        for row in rows:
            repo.insert_reading(conn, row)
        counts[machine["machine_id"]] = len(rows)

    if not existing:  # first seed: sample files + inspection/audit history
        _write_sample_csv(all_rows)
        _seed_inspections(conn)
        repo.record_audit(conn, "seed", "seed_run", "system", "database",
                          {"machines": list(counts), "readings": sum(counts.values())})
    conn.commit()
    conn.close()
    counts["skipped_existing"] = sorted(existing)
    return counts


def _write_sample_csv(rows):
    DATA_DIR.mkdir(exist_ok=True)
    fields = ["machine_id", "timestamp", "temperature_c", "vibration_mm_s",
              "motor_load_percent", "rpm", "operating_hours", "data_source"]
    with (DATA_DIR / "sample_sensor_readings.csv").open("w", newline="",
                                                        encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{**r, "timestamp": r["timestamp"].isoformat(sep=" ")}
                          for r in rows])


def _seed_inspections(conn):
    rows = [
        dict(machine_id="BRG-001", inspection_date="2026-10-18", inspector="Priya",
             findings="Bearing running hot, lubrication topped up",
             component_condition="worn", action_taken="Re-lubricated, monitoring",
             resolution_status="open"),
        dict(machine_id="MIX-001", inspection_date="2026-10-16", inspector="Dan",
             findings="No abnormal findings",
             component_condition="good", action_taken="None required",
             resolution_status="closed"),
    ]
    for row in rows:
        repo.insert_inspection(conn, row)
        repo.record_audit(conn, "seed", "inspection_recorded", "machine",
                          row["machine_id"], row["inspection_date"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Seed the MaintAI demo database")
    parser.add_argument("--force", action="store_true",
                        help="seed even if ENABLE_SYNTHETIC_DATA is false")
    args = parser.parse_args()
    result = seed(force=args.force)
    print(json.dumps(result, indent=2, default=str))