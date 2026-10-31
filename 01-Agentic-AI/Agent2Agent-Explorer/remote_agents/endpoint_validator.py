"""Validate the endpoint advertised by a validated Agent Card.

Staged checks per instructions §10: card / protocol / endpoint / auth are
reported independently — a fetched card alone is never "CONNECTED".
"""
from dataclasses import dataclass

import httpx

from a2a.types import AgentInterface
from a2a.utils import TransportProtocol

from remote_agents.card_validator import ValidatedCard
from remote_agents.config import settings
from remote_agents.url_safety import UnsafeUrlError, validate_url

# What our installed SDK client can actually speak (gRPC extra not installed).
SUPPORTED_BINDINGS = frozenset({TransportProtocol.JSONRPC, TransportProtocol.HTTP_JSON})


class UnsupportedTransportError(Exception):
    """No advertised interface uses a transport this client supports."""


@dataclass
class EndpointReport:
    """One status line per stage; task_execution stays NOT TESTED until Phase 4."""

    card: str = "VALID"
    protocol: str = "UNKNOWN"
    endpoint: str = "NOT CHECKED"
    authentication: str = "NONE REQUIRED"
    task_execution: str = "NOT TESTED"
    interface: AgentInterface | None = None

    @property
    def task_ready(self) -> bool:
        return self.protocol == "SUPPORTED" and self.endpoint == "REACHABLE"

    def display(self) -> str:
        return "\n".join(
            [
                f"Agent Card:       {self.card}",
                f"Protocol:         {self.protocol}",
                f"Endpoint:         {self.endpoint}",
                f"Authentication:   {self.authentication}",
                f"Task execution:   {self.task_execution}",
            ]
        )


def select_interface(vc: ValidatedCard) -> AgentInterface:
    """Return the first advertised interface we can speak. Never guesses URLs."""
    for iface in vc.card.supported_interfaces:
        if iface.url and iface.protocol_binding in SUPPORTED_BINDINGS:
            return iface
    advertised = [i.protocol_binding or "?" for i in vc.card.supported_interfaces]
    raise UnsupportedTransportError(
        f"agent only advertises unsupported transports {advertised}; this client speaks {sorted(SUPPORTED_BINDINGS)}"
    )


def check_endpoint(vc: ValidatedCard, *, transport: httpx.BaseTransport | None = None) -> EndpointReport:
    """Run the staged validation and return an EndpointReport (never raises)."""
    report = EndpointReport()
    if vc.card.security_schemes:
        report.authentication = f"REQUIRED ({', '.join(vc.card.security_schemes)})"

    try:
        iface = select_interface(vc)
    except UnsupportedTransportError as exc:
        report.protocol = f"UNSUPPORTED - {exc}"
        return report
    report.protocol = "SUPPORTED"
    report.interface = iface

    try:
        validate_url(iface.url)
    except UnsafeUrlError as exc:
        report.endpoint = f"BLOCKED - {exc}"
        return report

    try:
        # ponytail: any HTTP response = reachable; a JSONRPC endpoint may 405 a bare GET
        with httpx.Client(follow_redirects=False, timeout=settings.default_timeout, transport=transport) as client:
            client.get(iface.url)
        report.endpoint = "REACHABLE"
    except httpx.HTTPError as exc:
        report.endpoint = f"UNREACHABLE - {exc}"
    return report
