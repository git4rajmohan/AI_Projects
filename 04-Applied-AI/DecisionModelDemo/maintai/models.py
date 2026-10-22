# Domain models + sensor validation (spec1 §7). Persistence fields
# (effective_from/version) live in the database layer, not here.

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ValidationError, field_validator, model_validator

# Demonstration plausible ranges — not universal sensor specs (spec1 §7).
RANGES = {
    "temperature_c": (-50.0, 200.0),
    "vibration_mm_s": (0.0, 100.0),
    "motor_load_percent": (0.0, 120.0),
    "rpm": (0.0, 10_000.0),
    "operating_hours": (0.0, 1_000_000.0),
}
ACCEPTED_TEMPERATURE_UNITS = {"c", "°c", "celsius"}
ACCEPTED_VIBRATION_UNITS = {"mm/s", "mm/s²"}  # velocity is the demo standard


class Machine(BaseModel):
    machine_id: str
    machine_name: str = ""
    machine_type: str = ""
    location: str = ""
    team: str = ""
    status: str = "active"


class MachineLimits(BaseModel):
    """Per-machine thresholds. Defaults are demonstration values (spec1 §5.3
    example + demo warnings) — the registry/seed sets real per-machine limits."""

    temperature_warning: float = 75.0
    temperature_critical: float = 90.0
    vibration_warning: float = 3.5
    vibration_critical: float = 4.5
    motor_load_warning: float = 75.0
    motor_load_critical: float = 85.0

    @model_validator(mode="after")
    def _each_warning_below_critical(self):
        pairs = [
            (self.temperature_warning, self.temperature_critical, "temperature"),
            (self.vibration_warning, self.vibration_critical, "vibration"),
            (self.motor_load_warning, self.motor_load_critical, "motor load"),
        ]
        for warn, crit, name in pairs:
            if warn >= crit:
                raise ValueError(f"{name} warning ({warn}) must be below critical ({crit})")
        return self


class SensorReading(BaseModel):
    machine_id: str
    timestamp: datetime
    # None means "sensor did not report" — never interpreted as zero (spec1 §7).
    temperature_c: Optional[float] = None
    vibration_mm_s: Optional[float] = None
    motor_load_percent: Optional[float] = None
    rpm: Optional[float] = None
    operating_hours: Optional[float] = None
    sensor_id: str = ""
    machine_type: str = ""
    temperature_unit: str = "C"
    vibration_unit: str = "mm/s"
    data_source: str = ""
    inspection_notes: str = ""

    @field_validator(*RANGES)
    @classmethod
    def _finite_in_range(cls, v, info):
        if v is None:
            return v
        if not math.isfinite(v):
            raise ValueError(f"{info.field_name} must be a finite number")
        lo, hi = RANGES[info.field_name]
        if not lo <= v <= hi:
            raise ValueError(f"{info.field_name} outside plausible range [{lo}, {hi}]")
        return v

    @model_validator(mode="after")
    def _units_supported(self):
        tu = self.temperature_unit.strip().lower().replace("°", "")
        vu = self.vibration_unit.strip().lower().replace("²", "")
        self.temperature_unit = "C" if tu in ACCEPTED_TEMPERATURE_UNITS else self.temperature_unit
        self.vibration_unit = "mm/s" if vu in ACCEPTED_VIBRATION_UNITS else self.vibration_unit
        if tu not in ACCEPTED_TEMPERATURE_UNITS:
            raise ValueError(
                f"temperature_unit '{self.temperature_unit}' not supported (expected C)"
            )
        if vu not in ACCEPTED_VIBRATION_UNITS:
            raise ValueError(
                f"vibration_unit '{self.vibration_unit}' not supported (expected mm/s)"
            )
        return self


class MachineState(BaseModel):
    """Container passed down the pipeline: validated reading + limits, filled
    with trends/alerts by the rules engine."""

    reading: SensorReading
    limits: MachineLimits
    trends: dict[str, Any] = {}
    alerts: list[str] = []


@dataclass
class ValidationResult:
    status: str  # valid | stale | missing_data | invalid
    reasons: list[str] = field(default_factory=list)
    reading: Optional[SensorReading] = None

    @property
    def ok(self):
        return self.status == "valid"


SENSOR_FIELDS = tuple(RANGES)


def _now_like(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return datetime.now()
    return datetime.now(ts.tzinfo)


def validate_reading(reading, limits, freshness_minutes: float) -> ValidationResult:
    """Validate one reading: types/units/ranges/finiteness via the model, then
    staleness and missing-data status. Never zero-fills missing sensors."""
    try:
        parsed = (
            reading
            if isinstance(reading, SensorReading)
            else SensorReading.model_validate(reading)
        )
    except ValidationError as e:
        return ValidationResult(
            "invalid",
            [f"{'.'.join(str(p) for p in err['loc']) or 'reading'}: {err['msg']}"
             for err in e.errors()],
        )

    ts = parsed.timestamp
    now = _now_like(ts)
    reasons = []
    if ts > now + timedelta(minutes=5):  # small clock-skew tolerance
        return ValidationResult("invalid", ["timestamp is in the future"])

    missing = [f for f in SENSOR_FIELDS if getattr(parsed, f) is None]
    late = ts < now - timedelta(minutes=freshness_minutes)
    if missing:
        return ValidationResult(
            "missing_data", [f"{name} missing" for name in missing], parsed
        )
    if late:
        return ValidationResult(
            "stale",
            [f"timestamp older than the {freshness_minutes}-minute freshness window"],
            parsed,
        )
    return ValidationResult("valid", [], parsed)


def find_duplicates(rows: Iterable[Any]) -> list[tuple[str, datetime]]:
    """Return (machine_id, timestamp) keys appearing more than once."""
    counts = Counter((r.machine_id, r.timestamp) for r in rows)
    return [key for key, n in counts.items() if n > 1]