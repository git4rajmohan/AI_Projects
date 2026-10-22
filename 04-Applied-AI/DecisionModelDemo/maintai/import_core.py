# Data-import core (spec1 §7 CSV upload; plan Phase 12): parse a CSV into row
# dicts, classify each row (valid / quarantined + reason / in-file duplicate).
# Pure functions — no Streamlit, no db — so the page stays thin and the logic
# is unit-testable (plan 12.V).

import csv
import io
from datetime import datetime

from pydantic import ValidationError

from config.settings import SENSOR_FRESHNESS_MINUTES
from maintai.models import SensorReading, validate_reading

REQUIRED_COLUMNS = ("machine_id", "timestamp", "temperature_c", "vibration_mm_s",
                    "motor_load_percent", "rpm", "operating_hours")


def parse_csv(text: str) -> list[dict]:
    """CSV text -> row dicts. Raises ValueError with an actionable message
    (spec1 §14: CSV parsing errors)."""
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV: {exc}") from exc
    if reader.fieldnames is None:
        raise ValueError("The uploaded file is empty.")
    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing)
                         + f". Required columns: {', '.join(REQUIRED_COLUMNS)}")
    return rows


def classify_rows(rows: list[dict], source_name: str,
                  freshness_minutes: float = SENSOR_FRESHNESS_MINUTES) -> dict:
    """Per-row validation with the Phase-1 validator.

    Returns:
      valid: dicts ready for repo.insert_reading (data_source=filename)
      quarantined: [(original_row, reason)]
      in_file_dupes: [(line_no, machine_id, timestamp)]
      machine_ids: sorted distinct ids of the valid rows (for the db report)
    Stale/missing_data rows are quarantined too — importing a row the
    pipeline would immediately reject is noise; the reason says which.
    """
    valid, quarantined = [], []
    in_file_dupes = []
    seen = set()
    machine_ids = set()
    for i, row in enumerate(rows, start=2):  # line 1 is the header
        try:
            ts = datetime.fromisoformat(row.get("timestamp") or "")
        except (ValueError, TypeError):
            quarantined.append((row, f"line {i}: unparseable timestamp "
                                     f"{row.get('timestamp')!r}"))
            continue
        key = (row.get("machine_id") or "", ts)
        if key in seen:
            in_file_dupes.append((i, key[0], ts))
            quarantined.append((row, f"line {i}: duplicate timestamp {ts} "
                                     f"for {key[0]} (already in this file)"))
            continue
        try:
            reading = SensorReading.model_validate({
                "machine_id": key[0], "timestamp": ts,
                "temperature_c": _num(row.get("temperature_c")),
                "vibration_mm_s": _num(row.get("vibration_mm_s")),
                "motor_load_percent": _num(row.get("motor_load_percent")),
                "rpm": _num(row.get("rpm")),
                "operating_hours": _num(row.get("operating_hours")),
                "data_source": source_name,
            })
        except ValidationError as exc:
            err = exc.errors()[0]
            loc = ".".join(str(p) for p in err["loc"]) or "reading"
            quarantined.append((row, f"line {i} [invalid]: {loc}: {err['msg']}"))
            continue
        validation = validate_reading(reading, limits=None,
                                      freshness_minutes=freshness_minutes)
        if not validation.ok:
            quarantined.append((row, f"line {i} [{validation.status}]: "
                                     + "; ".join(validation.reasons)))
            continue
        seen.add(key)
        machine_ids.add(key[0])
        valid.append({"machine_id": key[0], "timestamp": ts,
                      "temperature_c": reading.temperature_c,
                      "vibration_mm_s": reading.vibration_mm_s,
                      "motor_load_percent": reading.motor_load_percent,
                      "rpm": reading.rpm,
                      "operating_hours": reading.operating_hours,
                      "data_source": source_name,
                      "validation_status": validation.status})
    return {"valid": valid, "quarantined": quarantined,
            "in_file_dupes": in_file_dupes, "machine_ids": sorted(machine_ids)}


def _num(value):
    """CSV cell -> float or None. Blank/non-numeric means 'sensor absent',
    which the Phase-1 validator reports as missing_data, never zero (§7)."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return value  # pydantic produces the reason