"""Endpoint validation tests: mocked transport + mocked DNS, zero network."""
import socket

import httpx
import pytest

from remote_agents.card_validator import validate_card
from remote_agents.endpoint_validator import (
    UnsupportedTransportError,
    check_endpoint,
    select_interface,
)

URL = "https://agent.example/.well-known/agent-card.json"


def card_with(interfaces: list[dict], **extra) -> dict:
    return {
        "name": "X",
        "description": "d",
        "version": "1.0.0",
        "supported_interfaces": interfaces,
        "default_input_modes": ["text/plain"],
        "default_output_modes": ["text/plain"],
        "capabilities": {},
        "skills": [{"id": "s", "name": "S", "description": "d", "tags": ["t"]}],
        **extra,
    }


JSONRPC = {"url": "https://agent.example/a2a", "protocol_binding": "JSONRPC", "protocol_version": "1.0"}
GRPC_ONLY = {"url": "https://agent.example/grpc", "protocol_binding": "GRPC", "protocol_version": "1.0"}


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    import ipaddress

    def fake(host, *a, **k):
        try:
            ip = str(ipaddress.ip_address(host))  # keep literal IPs as-is
        except ValueError:
            ip = "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def test_supported_interface_selected():
    vc = validate_card(card_with([GRPC_ONLY, JSONRPC]), URL)
    assert select_interface(vc).protocol_binding == "JSONRPC"


def test_unsupported_transport_rejected():
    vc = validate_card(card_with([GRPC_ONLY]), URL)
    with pytest.raises(UnsupportedTransportError, match="GRPC"):
        select_interface(vc)
    report = check_endpoint(vc)
    assert report.protocol.startswith("UNSUPPORTED")
    assert report.endpoint == "NOT CHECKED"
    assert not report.task_ready


def test_reachable_endpoint(monkeypatch):
    vc = validate_card(card_with([JSONRPC]), URL)
    t = httpx.MockTransport(lambda req: httpx.Response(405))  # bare GET on JSONRPC endpoint
    report = check_endpoint(vc, transport=t)
    assert report.card == "VALID"
    assert report.protocol == "SUPPORTED"
    assert report.endpoint == "REACHABLE"
    assert report.task_execution == "NOT TESTED"
    assert report.task_ready


def test_unreachable_endpoint():
    vc = validate_card(card_with([JSONRPC]), URL)

    def down(req):
        raise httpx.ConnectError("connection refused")

    report = check_endpoint(vc, transport=httpx.MockTransport(down))
    assert report.protocol == "SUPPORTED"  # stages independent
    assert report.endpoint.startswith("UNREACHABLE")
    assert not report.task_ready


def test_private_endpoint_blocked():
    private = dict(JSONRPC, url="https://10.0.0.5/a2a")
    vc = validate_card(card_with([private]), URL)
    report = check_endpoint(vc)
    assert report.protocol == "SUPPORTED"
    assert report.endpoint.startswith("BLOCKED")
    assert not report.task_ready


def test_auth_requirement_reported():
    data = card_with(
        [JSONRPC],
        security_schemes={"bearer": {"http_auth_security_scheme": {"scheme": "bearer"}}},
    )
    vc = validate_card(data, URL)
    report = check_endpoint(vc, transport=httpx.MockTransport(lambda r: httpx.Response(405)))
    assert "REQUIRED" in report.authentication
    assert "bearer" in report.authentication


def test_display_has_all_stages():
    vc = validate_card(card_with([JSONRPC]), URL)
    text = check_endpoint(vc, transport=httpx.MockTransport(lambda r: httpx.Response(200))).display()
    for label in ("Agent Card:", "Protocol:", "Endpoint:", "Authentication:", "Task execution:"):
        assert label in text
