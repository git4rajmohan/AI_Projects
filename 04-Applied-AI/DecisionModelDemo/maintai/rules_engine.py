# Deterministic rules engine (spec1 §6). Pure Python — no LLM anywhere here.
# Trend helpers live here (plan deviation note 3); outputs feed both the Tev1
# state builder and the policy engine verbatim.

from dataclasses import dataclass, field
from typing import Optional

from config.settings import (MOTOR_LOAD_ROC_PCT_PER_H, TEMPERATURE_ROC_C_PER_H,
                             TREND_WINDOW_READINGS, VIBRATION_ROC_MM_S_PER_H)
from maintai.models import MachineLimits, SensorReading

# The three channels the policy engine reasons about.
CHANNELS = ("temperature_c", "vibration_mm_s", "motor_load_percent")

ALERTS = {
    "temperature_c": ("Temperature warning threshold exceeded",
                      "Critical temperature threshold exceeded"),
    "vibration_mm_s": ("Vibration warning threshold exceeded",
                       "Critical vibration threshold exceeded"),
    "motor_load_percent": ("Motor load warning threshold exceeded",
                           "Critical motor load threshold exceeded"),
}
MISSING_LABELS = {"temperature_c": "Temperature reading missing",
                  "vibration_mm_s": "Vibration reading missing",
                  "motor_load_percent": "Motor load reading missing"}
ROC_LIMITS = {"temperature_c": TEMPERATURE_ROC_C_PER_H,
              "vibration_mm_s": VIBRATION_ROC_MM_S_PER_H,
              "motor_load_percent": MOTOR_LOAD_ROC_PCT_PER_H}
ROC_LABELS = {"temperature_c": "Rate of temperature change above threshold",
              "vibration_mm_s": "Rate of vibration change above threshold",
              "motor_load_percent": "Rate of motor load change above threshold"}


@dataclass
class RuleReport:
    alerts: list[str] = field(default_factory=list)
    critical_breaches: list[str] = field(default_factory=list)  # channel names
    deviations: dict[str, Optional[float]] = field(default_factory=dict)
    trends: dict[str, Optional[str]] = field(default_factory=dict)
    mandatory_escalation: bool = False


def classify_trend(series: list[float]) -> Optional[str]:
    """increasing / decreasing / stable over the observed window (None if too few).
    ponytail: first-vs-last sign test — a least-squares fit if the demo needs it."""
    usable = [v for v in series if v is not None]
    if len(usable) < 3:
        return None
    change = usable[-1] - usable[0]
    span = abs(usable[0]) or 1.0
    if change > 0.05 * span:
        return "increasing"
    if change < -0.05 * span:
        return "decreasing"
    return "stable"


def rate_of_change(series: list, hours: float) -> Optional[float]:
    """(last - first) / hours, skipping gaps between distinct readings."""
    usable = [(v) for v in series if v is not None]
    if len(usable) < 2 or hours <= 0:
        return None
    return (usable[-1] - usable[0]) / hours


def evaluate_machine(reading: SensorReading, limits: MachineLimits,
                     history: list[SensorReading] = (),
                     mandatory_escalation: bool = False) -> RuleReport:
    """Deterministic threshold + rate-of-change checks (spec1 §6.1–6.3)."""
    report = RuleReport(mandatory_escalation=mandatory_escalation)
    pairs = {
        "temperature_c": (reading.temperature_c, limits.temperature_warning,
                          limits.temperature_critical),
        "vibration_mm_s": (reading.vibration_mm_s, limits.vibration_warning,
                           limits.vibration_critical),
        "motor_load_percent": (reading.motor_load_percent,
                               limits.motor_load_warning, limits.motor_load_critical),
    }
    for channel, (value, warn, crit) in pairs.items():
        if value is None:
            report.alerts.append(MISSING_LABELS[channel])
            continue
        # deviation = overshoot above the warning line, relative to range span
        span_crit = max(crit * 1.5, crit + 1.0)
        report.deviations[channel] = round(max(0.0, (value - warn) / span_crit), 3)
        if value >= crit:
            report.alerts.append(ALERTS[channel][1])
            report.critical_breaches.append(channel)
        elif value >= warn:
            report.alerts.append(ALERTS[channel][0])

    if history:  # trends + ROC over the observed window
        window = list(history)[- TREND_WINDOW_READINGS:]
        hours = (window[-1].timestamp - window[0].timestamp).total_seconds() / 3600
        for channel in CHANNELS:
            series = [getattr(r, channel) for r in window]
            report.trends[channel] = classify_trend(series)
            roc = rate_of_change(series, hours)
            if roc is not None and abs(roc) >= ROC_LIMITS[channel]:
                report.alerts.append(ROC_LABELS[channel])
    return report