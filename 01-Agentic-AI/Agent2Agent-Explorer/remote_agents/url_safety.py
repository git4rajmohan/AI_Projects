"""SSRF protection: validate user-supplied URLs before any network request.

All outbound fetches (agent cards, endpoints) must pass validate_url() first.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from remote_agents.config import settings


class UnsafeUrlError(ValueError):
    """URL failed a safety check; message says why."""


def _resolve(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"DNS resolution failed for {hostname!r}: {exc}") from exc
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def validate_url(
    url: str,
    *,
    require_https: bool | None = None,
    allow_local: bool | None = None,
    allowed_domains: frozenset[str] | None = None,
) -> str:
    """Raise UnsafeUrlError unless `url` is safe to fetch. Returns the hostname.

    Blocks non-HTTP(S) schemes, plain HTTP (unless allowed), loopback/private/
    link-local/multicast/reserved addresses (covers cloud metadata IPs), and
    hosts outside the optional domain allowlist. DNS is resolved and every
    resolved address is checked.
    """
    require_https = settings.require_https if require_https is None else require_https
    allow_local = settings.allow_local_agents if allow_local is None else allow_local
    allowed_domains = settings.allowed_domains if allowed_domains is None else allowed_domains

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"unsupported scheme {parsed.scheme!r}; only https (and http in local mode) allowed")
    if parsed.scheme == "http" and require_https and not allow_local:
        raise UnsafeUrlError("HTTPS is required (set ALLOW_LOCAL_AGENTS=true only for local development)")
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL has no hostname")
    if allowed_domains and hostname.lower() not in allowed_domains:
        raise UnsafeUrlError(f"host {hostname!r} is not in the configured allowlist")

    for ip in _resolve(hostname):
        if ip.is_loopback and allow_local:
            continue  # ponytail: dev mode permits loopback only; metadata/private stay blocked
        if not ip.is_global:
            raise UnsafeUrlError(
                f"host {hostname!r} resolves to non-public address {ip} (loopback/private/link-local/reserved blocked)"
            )
    return hostname
