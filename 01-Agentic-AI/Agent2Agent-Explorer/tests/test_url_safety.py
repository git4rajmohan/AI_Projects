"""SSRF checks. No network: literal-IP URLs need no DNS; hostname tests mock getaddrinfo."""
import socket

import pytest

from remote_agents import url_safety
from remote_agents.url_safety import UnsafeUrlError, validate_url

PROD = dict(require_https=True, allow_local=False, allowed_domains=frozenset())
DEV = dict(require_https=True, allow_local=True, allowed_domains=frozenset())


def fake_dns(ip: str):
    return lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def test_http_rejected_in_prod():
    with pytest.raises(UnsafeUrlError, match="HTTPS"):
        validate_url("http://example.com/card.json", **PROD)


def test_non_http_scheme_rejected():
    with pytest.raises(UnsafeUrlError, match="scheme"):
        validate_url("file:///etc/passwd", **PROD)


def test_localhost_rejected_in_prod():
    with pytest.raises(UnsafeUrlError):
        validate_url("https://127.0.0.1/card.json", **PROD)


def test_private_ip_rejected():
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_url("https://10.0.0.5/card.json", **PROD)


def test_metadata_ip_rejected_even_in_dev():
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_url("https://169.254.169.254/latest/meta-data", **DEV)


def test_localhost_allowed_in_dev():
    assert validate_url("http://127.0.0.1:9999/card.json", **DEV) == "127.0.0.1"


def test_public_https_passes(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns("93.184.216.34"))
    assert validate_url("https://example.com/card.json", **PROD) == "example.com"


def test_dns_to_private_ip_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns("192.168.1.10"))
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_url("https://evil.example/card.json", **PROD)


def test_dns_failure_rejected(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(UnsafeUrlError, match="DNS"):
        validate_url("https://no-such-host.example/", **PROD)


def test_allowlist_enforced(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns("93.184.216.34"))
    allow = dict(require_https=True, allow_local=False, allowed_domains=frozenset({"trusted.example"}))
    assert validate_url("https://trusted.example/card.json", **allow) == "trusted.example"
    with pytest.raises(UnsafeUrlError, match="allowlist"):
        validate_url("https://other.example/card.json", **allow)
