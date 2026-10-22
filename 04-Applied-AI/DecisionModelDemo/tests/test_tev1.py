# Phase 11 — Tev1 service tests. All requests.post calls are monkeypatched:
# no network in the default run. Live tests live in test_live_smoke.py behind
# the RUN_LIVE_TESTS=1 flag (plan 11.2/11.6).

import requests

from services import tev1_service
from services.tev1_service import Tev1Error, call_tev1

from .conftest import FakeResponse

GOOD_ANSWER = {"type": "choice", "choice": "duplicate_charge",
               "probabilities": {"duplicate_charge": 0.98, "none": 0.02},
               "confidence": 0.98}
GOOD_QUESTIONS = {"intent": {"instructions": "Pick the intent.", "type": "choice",
                             "choices": ["duplicate_charge", "none"],
                             "criteria": {"duplicate_charge": "billed twice",
                                          "none": "no issue"}}}


def _capture(monkeypatch, resp):
    """Monkeypatch requests.post, return the list used by tests to inspect the call."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return resp

    monkeypatch.setattr(tev1_service.requests, "post", fake_post)
    return calls


def test_payload_construction_and_url(monkeypatch):
    calls = _capture(monkeypatch, FakeResponse(json_data={
        "model": tev1_service.TEV1_MODEL, "answers": {"intent": GOOD_ANSWER}}))
    call_tev1("my scenario", GOOD_QUESTIONS)
    url, kwargs = calls[0]
    assert url == f"{tev1_service.OLLAMA_HOST}/v1/systemone"  # plan 2.3b: NOT /api/chat
    assert "headers" not in kwargs                            # no auth needed locally
    body = kwargs["json"]
    assert body["model"] == tev1_service.TEV1_MODEL           # plan 11.3: model from env
    assert body["state"] == "my scenario"
    assert body["questions"] == GOOD_QUESTIONS


def test_happy_path_parse(monkeypatch):
    _capture(monkeypatch, FakeResponse(json_data={
        "model": "tev1:4b",
        "answers": {"intent": GOOD_ANSWER},
        "usage": {"input_tokens": 153, "output_tokens": 1}}))
    out = call_tev1("s", GOOD_QUESTIONS)
    assert out["model"] == "tev1:4b"
    assert out["answers"]["intent"]["choice"] == "duplicate_charge"
    assert out["answers"]["intent"]["confidence"] == 0.98
    assert out["answers"]["intent"]["probabilities"]["none"] == 0.02
    assert out["usage"] == {"input_tokens": 153, "output_tokens": 1}
    assert isinstance(out["elapsed_s"], float) and out["elapsed_s"] >= 0


def test_missing_optional_fields_stay_none(monkeypatch):
    # plan 11.3: absent usage/tokens must never be fabricated
    _capture(monkeypatch, FakeResponse(json_data={"answers": {"intent": GOOD_ANSWER}}))
    out = call_tev1("s", GOOD_QUESTIONS)
    assert "usage" not in out


def test_invalid_json(monkeypatch):
    _capture(monkeypatch, FakeResponse(status_code=200, text="<html>oops</html>"))
    try:
        call_tev1("s", GOOD_QUESTIONS)
        raise AssertionError("expected Tev1Error")
    except Tev1Error as e:
        assert "invalid" in str(e).lower()


def test_connection_error_friendly(monkeypatch):
    def fail_post(url, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(tev1_service.requests, "post", fail_post)
    try:
        call_tev1("s", GOOD_QUESTIONS)
        raise AssertionError("expected Tev1Error")
    except Tev1Error as e:
        assert tev1_service.OLLAMA_HOST in str(e) and "reachable" in str(e)


def test_timeout_friendly(monkeypatch):
    def fail_post(url, **kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(tev1_service.requests, "post", fail_post)
    try:
        call_tev1("s", GOOD_QUESTIONS)
        raise AssertionError("expected Tev1Error")
    except Tev1Error as e:
        assert "timed out" in str(e).lower()


def test_model_not_pulled_404(monkeypatch):
    _capture(monkeypatch, FakeResponse(status_code=404, json_data={
        "error": "model 'tev1:4b' not found"}))
    try:
        call_tev1("s", GOOD_QUESTIONS)
        raise AssertionError("expected Tev1Error")
    except Tev1Error as e:
        assert "ollama pull" in str(e).lower()


def test_other_http_status_friendly(monkeypatch):
    _capture(monkeypatch, FakeResponse(status_code=400, json_data={
        "error": "criteria must contain 2-26 candidates"}))
    try:
        call_tev1("s", GOOD_QUESTIONS)
        raise AssertionError("expected Tev1Error")
    except Tev1Error as e:
        assert "400" in str(e) and "criteria must contain 2-26 candidates" in str(e)


def test_answers_missing_or_wrong_shape(monkeypatch):
    _capture(monkeypatch, FakeResponse(json_data={"model": "tev1:4b"}))
    try:
        call_tev1("s", GOOD_QUESTIONS)
        raise AssertionError("expected Tev1Error")
    except Tev1Error as e:
        assert "answers" in str(e)

    _capture(monkeypatch, FakeResponse(json_data={"answers": []}))
    try:
        call_tev1("s", GOOD_QUESTIONS)
        raise AssertionError("expected Tev1Error")
    except Tev1Error as e:
        assert "answers" in str(e)