# Phase 1 — Data model + sensor validation tests (plan 1.V). Pure, no network/db.

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from maintai.models import (MachineLimits, SensorReading, find_duplicates,
                            validate_reading)


def make_reading(**over):
    base = dict(
        machine_id="BRG-001",
        timestamp=datetime.now().replace(second=0, microsecond=0),  # fresh vs system clock
        temperature_c=70.0,
        vibration_mm_s=3.0,
        motor_load_percent=70.0,
        rpm=1800.0,
        operating_hours=1200.0,
    )
    base.update(over)
    return base


LIMITS = MachineLimits()


def test_limits_warning_below_critical():
    with pytest.raises(ValidationError):
        MachineLimits(temperature_warning=95.0, temperature_critical=90.0)


def test_reading_field_ranges():
    SensorReading(**make_reading(temperature_c=-40.0))  # inside plausible range
    for field, bad in [("temperature_c", 999.0), ("vibration_mm_s", -1.0),
                       ("motor_load_percent", -5.0), ("rpm", 20000.0),
                       ("operating_hours", -1.0)]:
        with pytest.raises(ValidationError):
            SensorReading(**make_reading(**{field: bad}))


def test_non_finite_rejected():
    with pytest.raises(ValidationError):
        SensorReading(**make_reading(temperature_c=float("inf")))


def test_missing_values_stay_none_not_zero():
    r = SensorReading(**make_reading(rpm=None))
    assert r.rpm is None


def test_units():
    SensorReading(**make_reading(temperature_unit="°C", vibration_unit="mm/s²"))
    for kwargs in [(("temperature_unit",), {"temperature_unit": "F"}),
                   (("vibration_unit",), {"vibration_unit": "in/s"})]:
        field, kw = kwargs
        with pytest.raises(ValidationError, match="not supported"):
            SensorReading(**make_reading(**kw))


def test_valid_fresh_reading():
    res = validate_reading(make_reading(), LIMITS, freshness_minutes=180)
    assert res.status == "valid" and res.ok
    assert res.reading.temperature_c == 70.0


def test_stale_reading():
    old = datetime.now() - timedelta(hours=4)
    res = validate_reading(make_reading(timestamp=old), LIMITS, freshness_minutes=180)
    assert res.status == "stale" and "freshness" in res.reasons[0]


def test_missing_data_reading():
    res = validate_reading(make_reading(vibration_mm_s=None), LIMITS,
                           freshness_minutes=180)
    assert res.status == "missing_data"
    assert res.reasons == ["vibration_mm_s missing"]


def test_invalid_reading_types():
    res = validate_reading(make_reading(temperature_c="very hot"), LIMITS, 180)
    assert res.status == "invalid" and res.reasons


def test_future_timestamp_invalid():
    res = validate_reading(
        make_reading(timestamp=datetime.now() + timedelta(days=2)), LIMITS, 180
    )
    assert res.status == "invalid" and "future" in res.reasons[0]


def test_freshness_respects_tz_aware_timestamps():
    tz_now = datetime.now().astimezone()
    fresh = tz_now - timedelta(minutes=10)
    res = validate_reading(make_reading(timestamp=fresh), LIMITS, 180)
    assert res.status == "valid"


def test_duplicate_detection():
    now = datetime.now().replace(second=0, microsecond=0)
    rows = [SensorReading(**make_reading(timestamp=now)),
            SensorReading(**make_reading(timestamp=now)),
            SensorReading(**make_reading(timestamp=now + timedelta(hours=1)))]
    dupes = find_duplicates(rows)
    assert dupes == [("BRG-001", now)]