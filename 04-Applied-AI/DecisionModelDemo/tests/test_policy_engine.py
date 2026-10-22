# Phase 6 — policy precedence tests (plan 6.V), one per rung + table order proof.

from datetime import datetime

from maintai.models import MachineLimits, SensorReading, ValidationResult
from maintai.maintenance_service import PolicyOutcome, apply_policy
from maintai.prompts import Tev1Decision
from maintai.rules_engine import RuleReport, evaluate_machine

LIMITS = MachineLimits()
GOOD = ValidationResult("valid", [])


def report(temperature_c=70.0, mandatory=False):
    return evaluate_machine(
        SensorReading(machine_id="B", timestamp=datetime.now(),
                      temperature_c=temperature_c, vibration_mm_s=3.0,
                      motor_load_percent=70.0), LIMITS,
        mandatory_escalation=mandatory)


def tev1(action="monitor", confidence=0.98, anomaly=0.1):
    return Tev1Decision(action=action, action_confidence=confidence,
                        anomaly_probability=anomaly)


# rung 1: invalid / stale / missing data
def test_invalid_data_first():
    out = apply_policy(ValidationResult("invalid", ["bad unit"]), report(95.0), tev1())
    assert out.outcome == PolicyOutcome.DATA_REVIEW
    assert out.human_review_required and out.final_action == "insufficient_data"


def test_stale_data():
    out = apply_policy(ValidationResult("stale", ["old"]), report(), tev1())
    assert out.outcome == PolicyOutcome.DATA_REVIEW


def test_missing_data():
    out = apply_policy(ValidationResult("missing_data", ["vibration missing"]),
                       report(), tev1())
    assert out.outcome == PolicyOutcome.DATA_REVIEW and out.human_review_required


# rung 2: mandatory escalation
def test_mandatory_escalation_beats_everything():
    out = apply_policy(GOOD, report(mandatory=True), tev1("urgent_maintenance"))
    assert out.outcome == PolicyOutcome.URGENT
    assert out.reason == "Machine policy mandates human escalation"


# rung 3: critical thresholds override the model
def test_critical_beats_monitor():
    out = apply_policy(GOOD, report(temperature_c=95.0), tev1("monitor", 0.99))
    assert out.outcome == PolicyOutcome.URGENT
    assert "temperature_c" in out.reason


# rung 4: Tev1 unavailable
def test_missing_tev1_decision():
    out = apply_policy(GOOD, report(), None)
    assert out.outcome == PolicyOutcome.UNAVAILABLE
    assert out.human_review_required


def test_tev1_action_none():
    out = apply_policy(GOOD, report(), tev1(action=None))
    assert out.outcome == PolicyOutcome.UNAVAILABLE


def test_tev1_insufficient_data_requires_review():
    out = apply_policy(GOOD, report(), tev1("insufficient_data", confidence=0.99))
    assert out.outcome == PolicyOutcome.REVIEW and out.human_review_required


# rung 5: low confidence / conflict
def test_low_confidence_review():
    out = apply_policy(GOOD, report(), tev1("monitor", confidence=0.55, anomaly=0.1))
    assert out.outcome == PolicyOutcome.REVIEW
    assert "below review threshold" in out.reason


def test_monitor_conflicting_with_anomaly():
    out = apply_policy(GOOD, report(), tev1("monitor", confidence=0.9, anomaly=0.8))
    assert out.outcome == PolicyOutcome.REVIEW
    assert "conflicts" in out.reason


def test_conflict_only_for_monitor_not_inspect():
    # inspect + anomaly evidence is coherent -> falls through to auto-accept
    out = apply_policy(GOOD, report(), tev1("inspect", confidence=0.9, anomaly=0.8))
    assert out.outcome == PolicyOutcome.AUTO


# rung 6: accept classification
def test_accept_monitor():
    out = apply_policy(GOOD, report(), tev1("monitor", confidence=0.98, anomaly=0.1))
    assert out.outcome == PolicyOutcome.AUTO
    assert out.final_action == "monitor" and not out.human_review_required


def test_accept_urgent_still_flags_review():
    out = apply_policy(GOOD, report(), tev1("urgent_maintenance", confidence=0.9))
    assert out.outcome == PolicyOutcome.AUTO and out.human_review_required


# precedence order proof: worse data outranks an escalation request
def test_order_data_outranks_escalation():
    out = apply_policy(ValidationResult("stale", ["old"]), report(mandatory=True),
                       tev1("urgent_maintenance", 0.99))
    assert out.outcome == PolicyOutcome.DATA_REVIEW