# Phase 4 — rules engine tests (plan 4.V). Pure + deterministic.

from datetime import datetime, timedelta

from maintai.models import MachineLimits, SensorReading
from maintai.rules_engine import (classify_trend, evaluate_machine, rate_of_change)

LIMITS = MachineLimits()  # demo: temp 75/90, vib 3.5/4.5, load 75/85


def reading(**over):
    base = dict(machine_id="BRG-001", timestamp=datetime.now().replace(microsecond=0),
                temperature_c=70.0, vibration_mm_s=3.0, motor_load_percent=70.0,
                rpm=1800.0, operating_hours=1200.0)
    base.update(over)
    return SensorReading(**base)


def test_all_within_limits():
    report = evaluate_machine(reading(), LIMITS)
    assert report.alerts == [] and report.critical_breaches == []
    assert report.mandatory_escalation is False


def test_temperature_warning_only():
    report = evaluate_machine(reading(temperature_c=80.0), LIMITS)
    assert report.alerts == ["Temperature warning threshold exceeded"]
    assert report.critical_breaches == []


def test_temperature_at_critical_breaches():
    report = evaluate_machine(reading(temperature_c=90.0), LIMITS)
    assert "Critical temperature threshold exceeded" in report.alerts
    assert report.critical_breaches == ["temperature_c"]


def test_vibration_warning_only():
    report = evaluate_machine(reading(vibration_mm_s=3.8), LIMITS)
    assert report.alerts == ["Vibration warning threshold exceeded"]


def test_multiple_sensor_warnings():
    report = evaluate_machine(reading(temperature_c=80.0, vibration_mm_s=4.0,
                                      motor_load_percent=80.0), LIMITS)
    assert len(report.alerts) == 3
    assert report.critical_breaches == []


def test_all_critical():
    report = evaluate_machine(reading(temperature_c=95.0, vibration_mm_s=7.2,
                                      motor_load_percent=91.0), LIMITS)
    assert report.critical_breaches == ["temperature_c", "vibration_mm_s",
                                        "motor_load_percent"]
    assert len(report.alerts) == 3


def test_missing_channel_alerts():
    report = evaluate_machine(reading(vibration_mm_s=None), LIMITS)
    assert report.alerts == ["Vibration reading missing"]


def test_roc_breach():
    now = datetime.now().replace(microsecond=0)
    # 7 readings over 6 h: (82-70)/6h = 2 °C/h — below the 10 °C/h ROC limit.
    # To breach 10 °C/h the rise must exceed 60 °C across the window.
    history = [reading(temperature_c=40 + 10 * i, timestamp=now - timedelta(hours=6 - i))
               for i in range(7)]  # (100-40)/6h = 10 °C/h → breach
    report = evaluate_machine(history[-1], LIMITS, history=history)
    assert "Rate of temperature change above threshold" in report.alerts


def test_classify_trend():
    assert classify_trend([70.0, 71.0, 73.0, 76.0]) == "increasing"
    assert classify_trend([90.0, 88.0, 85.0, 82.0]) == "decreasing"
    assert classify_trend([70.0, 70.3, 69.9, 70.1]) == "stable"
    assert classify_trend([70.0, 70.2]) is None  # too few points


def test_rate_of_change_math():
    assert rate_of_change([70.0, 82.0], 6.0) == 2.0
    assert rate_of_change([70.0], 6.0) is None
    assert rate_of_change([70.0, 82.0], 0) is None


def test_deterministic():
    r = reading(temperature_c=95.0)
    one = evaluate_machine(r, LIMITS, history=[r] * 5)
    two = evaluate_machine(r, LIMITS, history=[r] * 5)
    assert one.alerts == two.alerts and one.deviations == two.deviations


def test_mandatory_escalation_flag_passthrough():
    report = evaluate_machine(reading(), LIMITS, mandatory_escalation=True)
    assert report.mandatory_escalation and report.alerts == []


def test_deviations_monotonic():
    below = evaluate_machine(reading(temperature_c=74.0), LIMITS)
    warn = evaluate_machine(reading(temperature_c=80.0), LIMITS)
    crit = evaluate_machine(reading(temperature_c=95.0), LIMITS)
    assert below.deviations["temperature_c"] == 0.0
    assert 0 < warn.deviations["temperature_c"] < crit.deviations["temperature_c"]