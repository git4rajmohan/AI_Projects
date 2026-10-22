# Phase 11 — Ollama Cloud LLM service tests. All requests.post calls are
# monkeypatched: no network in the default run (plan 11.2/11.4).

import requests

from services import llm_service
from services.llm_service import LlmError, call_llm

from .conftest import FakeResponse

GOOD_MESSAGE = {"role": "assistant", "content": "OK"}


def _capture(monkeypatch, resp):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return resp

    monkeypatch.setattr(llm_service.requests, "post", fake_post)
    return calls


def test_model_host_from_env(monkeypatch):
    calls = _capture(monkeypatch, FakeResponse(json_data={
        "model": llm_service.OLLAMA_CLOUD_MODEL, "message": GOOD_MESSAGE}))
    out = call_llm("Say OK in one word.")
    url, kwargs = calls[0]
    assert url == f"{llm_service.OLLAMA_CLOUD_HOST}/api/chat"
    assert kwargs["json"]["model"] == llm_service.OLLAMA_CLOUD_MODEL  # from .env, not hard-coded
    assert kwargs["json"]["stream"] is False                          # MVP: non-streaming
    assert kwargs["json"]["messages"] == [{"role": "user",
                                           "content": "Say OK in one word."}]
    assert out["model"] == llm_service.OLLAMA_CLOUD_MODEL


def test_auth_header_present(monkeypatch):
    calls = _capture(monkeypatch, FakeResponse(json_data={
        "model": llm_service.OLLAMA_CLOUD_MODEL, "message": GOOD_MESSAGE}))
    call_llm("hi")
    headers = calls[0][1]["headers"]
    assert headers.get("Authorization") == f"Bearer {llm_service.OLLAMA_API_KEY}"


def test_text_extraction(monkeypatch):
    _capture(monkeypatch, FakeResponse(json_data={
        "model": "whatever", "message": GOOD_MESSAGE, "done_reason": "stop"}))
    out = call_llm("hi")
    assert out["text"] == "OK"                       # visible answer, not the thinking trace
    assert out["done_reason"] == "stop"
    assert isinstance(out["elapsed_s"], float) and out["elapsed_s"] >= 0


def test_token_fields_optional(monkeypatch):
    _capture(monkeypatch, FakeResponse(json_data={
        "model": "m", "message": GOOD_MESSAGE,
        "prompt_eval_count": 18, "eval_count": 70}))
    out = call_llm("hi")
    assert out["prompt_tokens"] == 18 and out["eval_tokens"] == 70

    _capture(monkeypatch, FakeResponse(json_data={"model": "m", "message": GOOD_MESSAGE}))
    out = call_llm("hi")
    assert out["prompt_tokens"] is None and out["eval_tokens"] is None  # never fabricated


def test_401_auth_message(monkeypatch):
    _capture(monkeypatch, FakeResponse(status_code=401, json_data={
        "error": "bad key"}, text="unauthorized"))
    try:
        call_llm("hi")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        msg = str(e)
        assert "OLLAMA_API_KEY" in msg
        # plan 10.3/3.6 discipline also holds under mockery: no key value in the message
        assert llm_service.OLLAMA_API_KEY not in msg
        assert "bad key" not in msg          # friendly text, not the raw body


def test_403_also_auth(monkeypatch):
    _capture(monkeypatch, FakeResponse(status_code=403, text="forbidden"))
    try:
        call_llm("hi")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert "OLLAMA_API_KEY" in str(e)


def test_404_model_not_found(monkeypatch):
    _capture(monkeypatch, FakeResponse(status_code=404,
                                       json_data={"error": "model not found"}))
    try:
        call_llm("hi")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert llm_service.OLLAMA_CLOUD_MODEL in str(e)   # plan 11.4 friendly wording
        assert "OLLAMA_CLOUD_MODEL" in str(e)


def test_timeout_and_connection(monkeypatch):
    def fail_timeout(url, **kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(llm_service.requests, "post", fail_timeout)
    try:
        call_llm("hi")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert "timed out" in str(e).lower()

    def fail_conn(url, **kwargs):
        raise requests.exceptions.ConnectionError("no route")

    monkeypatch.setattr(llm_service.requests, "post", fail_conn)
    try:
        call_llm("hi")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert llm_service.OLLAMA_CLOUD_HOST in str(e)


def test_other_status_and_empty_content(monkeypatch):
    _capture(monkeypatch, FakeResponse(status_code=500, text="boom"))
    try:
        call_llm("hi")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert "500" in str(e)

    _capture(monkeypatch, FakeResponse(json_data={
        "model": "m", "message": {"role": "assistant", "content": ""}}))
    try:
        call_llm("hi")
        raise AssertionError("expected LlmError")
    except LlmError as e:
        assert "empty" in str(e).lower()