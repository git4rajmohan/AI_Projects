# Phase 5 — maintenance Tev1 prompts + parser tests (plan 5.V). Mocked requests;
# live probe already performed against real Ollama 0.40.6 (sample saved).

from datetime import datetime

import pytest

import services.tev1_service as tev1_mod
from maintai.models import MachineLimits, SensorReading
from maintai.prompts import (QUESTIONS, Tev1Decision, build_state,
                             decision_request, interpret_tev1)
from maintai.rules_engine import evaluate_machine
from services.tev1_service import Tev1Error, call_tev1
from tests.conftest import FakeResponse

LIMITS = MachineLimits()


def reading(**over):
    base = dict(machine_id="BRG-001", timestamp=datetime.now().replace(microsecond=0),
                temperature_c=94.0, vibration_mm_s=7.2, motor_load_percent=91.0,
                rpm=1800.0, operating_hours=1200.0)
    base.update(over)
    return SensorReading(**base)


def report(**over):
    return evaluate_machine(reading(**over), LIMITS)


LIMIT_DICT = {"temperature": {"warning": 75, "critical": 90},
              "vibration": {"warning": 3.5, "critical": 4.5},
              "motor_load": {"warning": 75, "critical": 85},
              None: {}}


def test_payload_shape(monkeypatch):
    captured = {}
    monkeypatch.setattr(tev1_mod, "TEV1_TIMEOUT_SECONDS", 17)

    def fake_post(url, json=None, timeout=None):
        captured["url"], captured["json"], captured["timeout"] = url, json, timeout
        return FakeResponse(json_data={"model": "tev1:4b", "answers": {"maintenance_action": {"type": "choice", "choice": "inspect"}}})

    monkeypatch.setattr(tev1_mod.requests, "post", fake_post)
    call_tev1(**decision_request(report(), {"temperature_c": 94}, LIMIT_DICT))
    assert captured["timeout"] == 17
    assert captured["url"].endswith("/v1/systemone")
    assert captured["json"]["model"] == "tev1:4b"
    assert isinstance(captured["json"]["state"], str)
    qs = captured["json"]["questions"]
    assert set(qs) == {"maintenance_action", "anomaly_present", "severity"}
    assert qs["maintenance_action"]["choices"] == [
        "monitor", "inspect", "urgent_maintenance", "insufficient_data"]
    assert set(qs["maintenance_action"]["criteria"]) == set(qs["maintenance_action"]["choices"])
    assert qs["anomaly_present"]["type"] == "noul"
    assert qs["severity"]["type"] == "score"


def test_interpret_full_probe_response():
    # Real captured shapes (values from docs/samples/maintenance_tev1_response.json).
    result = {
        "model": "tev1:4b",
        "answers": {
            "maintenance_action": {
                "type": "choice", "choice": "urgent_maintenance",
                "probabilities": {"monitor": 0.0002, "inspect": 0.0226,
                                  "urgent_maintenance": 0.9682, "insufficient_data": 0.009},
                "confidence": 0.9576},
            "anomaly_present": {"type": "noul", "noul": 0.9965},
            "severity": {"type": "score", "score": 3.3166,
                         "legend": {"3": "Serious abnormality"},
                         "probabilities": {"3": 0.586}, "confidence": 0.6515},
        },
        "elapsed_s": 1.4,
    }
    d = interpret_tev1(result)
    assert d.action == "urgent_maintenance"
    assert d.action_confidence == 0.9576
    assert d.action_probabilities["urgent_maintenance"] == 0.9682
    assert d.anomaly_probability == 0.9965
    assert d.severity_score == pytest.approx(3.3166)
    assert d.severity_label == "Serious abnormality"
    assert d.model == "tev1:4b" and d.elapsed_s == 1.4


def test_interpret_never_fabricates_missing_fields():
    d = interpret_tev1({"answers": {}})
    assert d.action is None and d.action_confidence is None
    assert d.action_probabilities == {} and d.anomaly_probability is None
    assert d.severity_score is None and d.severity_label is None


def test_interpret_partial_answers():
    d = interpret_tev1({"answers": {"anomaly_present": {"type": "noul"}}})
    assert d.anomaly_probability is None  # missing "noul" key -> None


def test_build_state_content():
    state = build_state(report(), {"temperature_c": 94.0, "vibration_mm_s": 7.2,
                                   "motor_load_percent": 91.0}, LIMIT_DICT)
    assert "Temperature: 94 C (warning 75 C, critical 90 C)" in state
    assert "Motor load: 91 % (warning 75 %, critical 85 %)" in state
    assert "Rule alerts: " in state
    assert "monitor" not in state  # state carries evidence, never decisions


def test_build_state_missing_value():
    state = build_state(report(vibration_mm_s=None),
                        {"temperature_c": 70.0, "vibration_mm_s": None,
                         "motor_load_percent": 70.0}, LIMIT_DICT)
    assert "- Vibration: not reported" in state


def test_call_tev1_error_passthrough(monkeypatch):
    def fail(url, **kw):
        raise tev1_mod.requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(tev1_mod.requests, "post", fail)
    with pytest.raises(Tev1Error, match="not reachable"):
        call_tev1(**decision_request(report(), {"temperature_c": 94}, LIMIT_DICT))