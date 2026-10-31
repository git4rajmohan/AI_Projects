"""Card fetcher tests: mocked httpx transport + mocked DNS, zero network."""
import json
import socket

import httpx
import pytest

from remote_agents.card_fetcher import CardFetchError, fetch_card_json

URL = "https://agent.example/.well-known/agent-card.json"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


def transport_for(handler):
    return httpx.MockTransport(handler)


def test_valid_json_fetched():
    t = transport_for(lambda req: httpx.Response(200, json={"name": "X"}))
    assert fetch_card_json(URL, transport=t) == {"name": "X"}


def test_invalid_json_rejected():
    t = transport_for(lambda req: httpx.Response(200, content=b"<html>not json"))
    with pytest.raises(CardFetchError, match="not valid JSON"):
        fetch_card_json(URL, transport=t)


def test_non_object_json_rejected():
    t = transport_for(lambda req: httpx.Response(200, content=b'["list"]'))
    with pytest.raises(CardFetchError, match="not an object"):
        fetch_card_json(URL, transport=t)


def test_http_error_rejected():
    t = transport_for(lambda req: httpx.Response(404))
    with pytest.raises(CardFetchError, match="HTTP 404"):
        fetch_card_json(URL, transport=t)


def test_redirect_refused():
    t = transport_for(lambda req: httpx.Response(302, headers={"location": "https://evil.example/"}))
    with pytest.raises(CardFetchError, match="redirect"):
        fetch_card_json(URL, transport=t)


def test_oversized_body_rejected():
    big = json.dumps({"pad": "x" * 5000}).encode()
    t = transport_for(lambda req: httpx.Response(200, content=big))
    with pytest.raises(CardFetchError, match="byte limit"):
        fetch_card_json(URL, transport=t, max_bytes=1024)
