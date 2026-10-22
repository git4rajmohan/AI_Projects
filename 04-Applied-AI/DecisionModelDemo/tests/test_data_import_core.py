# Phase 12 — data-import core tests (plan 12.V): parsing, per-row
# classification, duplicates — pure functions, no db, no Streamlit.

from datetime import datetime, timedelta

import pytest

from maintai.import_core import classify_rows, parse_csv

FUTURE = (datetime.now() + timedelta(days=1)).isoformat(sep=" ")
FRESH = (datetime.now() - timedelta(minutes=10)).isoformat(sep=" ")
STALE = (datetime.now() - timedelta(days=2)).isoformat(sep=" ")

HEADER = ("machine_id,timestamp,temperature_c,vibration_mm_s,"
          "motor_load_percent,rpm,operating_hours\n")


def test_missing_column_actionable_error():
    text = "machine_id,timestamp,vibration_mm_s\nBRG-001,2026-10-01 00:00:00,2.5\n"
    with pytest.raises(ValueError) as exc:
        parse_csv(text)
    msg = str(exc.value)
    assert "temperature_c" in msg and "Required columns" in msg


def test_unparseable_csv_error():
    # field larger than the csv module's limit -> csv.Error (line too long)
    import csv as _csv
    big = "M" * (_csv.field_size_limit() + 10)
    text = f"machine_id,timestamp,temperature_c\nBRG-001,2026-10-01 00:00:00,{big}\n"
    with pytest.raises(ValueError) as exc:
        parse_csv(text)
    assert "Malformed CSV" in str(exc.value)


def test_empty_file_error():
    with pytest.raises(ValueError):
        parse_csv("")


def test_valid_rows_prepared_for_insert():
    rows = parse_csv(HEADER + f"BRG-001,{FRESH},70,2.5,60,1780,1000\n")
    report = classify_rows(rows, source_name="upload.csv")
    assert len(report["valid"]) == 1
    row = report["valid"][0]
    assert row["machine_id"] == "BRG-001"
    assert row["data_source"] == "upload.csv"       # filename preserved
    assert row["temperature_c"] == 70.0
    assert row["validation_status"] == "valid"
    assert report["quarantined"] == []
    assert report["machine_ids"] == ["BRG-001"]


def test_nan_units_future_rows_quarantined_with_reasons():
    text = (HEADER
            + f"BRG-001,{FRESH},,,60,1780,1000\n"        # NaN-ish empties
            + f"BRG-001,{FUTURE},70,2.5,60,1780,1000\n"  # future timestamp
            + f"BRG-001,{STALE},70,2.5,60,1780,1000\n")  # stale
    report = classify_rows(parse_csv(text), source_name="broken.csv")
    assert len(report["quarantined"]) == 3
    reasons = " | ".join(q[1] for q in report["quarantined"])
    assert "missing_data" in reasons and "temperature_c missing" in reasons
    assert "future" in reasons
    assert "stale" in reasons
    assert report["valid"] == []


def test_bad_number_quarantined():
    text = HEADER + f"BRG-001,{FRESH},hot,2.5,60,1780,1000\n"
    report = classify_rows(parse_csv(text), source_name="broken.csv")
    assert report["valid"] == []
    reason = report["quarantined"][0][1]
    assert "invalid" in reason and "temperature_c" in reason


def test_bad_timestamp_quarantined():
    text = HEADER + "BRG-001,not-a-time,70,2.5,60,1780,1000\n"
    report = classify_rows(parse_csv(text), source_name="broken.csv")
    reason = report["quarantined"][0][1]
    assert "unparseable timestamp" in reason


def test_in_file_duplicates_flagged():
    text = (HEADER + f"BRG-001,{FRESH},70,2.5,60,1780,1000\n"
            + f"BRG-001,{FRESH},71,2.6,61,1781,1001\n")  # same key twice
    report = classify_rows(parse_csv(text), source_name="dupes.csv")
    assert len(report["in_file_dupes"]) == 1
    line_no, machine, ts = report["in_file_dupes"][0]
    assert line_no == 3 and machine == "BRG-001"
    assert len(report["valid"]) == 1  # first instance kept
    assert "duplicate timestamp" in report["quarantined"][0][1]