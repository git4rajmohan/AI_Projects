"""Validate a fetched Agent Card dict against the installed a2a-sdk (1.3.0) schema."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from a2a.client.card_resolver import parse_agent_card
from a2a.types import AgentCard
from a2a.utils.proto_utils import validate_proto_required_fields


class CardValidationError(Exception):
    """Not a usable A2A Agent Card; message says why."""

    NOT_A2A = (
        "This endpoint is not a compatible A2A endpoint. "
        "It may be a website, REST API, MCP server, or unsupported protocol."
    )


@dataclass
class ValidatedCard:
    card: AgentCard
    source_url: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def validate_card(data: dict, source_url: str) -> ValidatedCard:
    """Parse + validate card JSON; raise CardValidationError with a clear reason."""
    try:
        card = parse_agent_card(data)  # SDK parser: handles compat, ignores unknown fields
        validate_proto_required_fields(card)
    except Exception as exc:
        fields = [e["field"] for e in getattr(exc, "data", {}).get("errors", [])] if hasattr(exc, "data") else []
        if not card_looks_like_a2a(data):
            raise CardValidationError(CardValidationError.NOT_A2A) from exc
        raise CardValidationError(f"Agent Card is missing required fields: {', '.join(fields) or exc}") from exc
    if not any(i.url for i in card.supported_interfaces):
        raise CardValidationError("Agent Card advertises no service endpoint (supported_interfaces empty)")
    return ValidatedCard(card=card, source_url=source_url)


def card_looks_like_a2a(data: dict) -> bool:
    """Heuristic to tell a broken card from a non-card (website/REST/MCP response)."""
    # ponytail: name + any known card key; refine if real-world cards trip it
    return "name" in data and any(
        k in data for k in ("supported_interfaces", "supportedInterfaces", "skills", "capabilities", "url", "version")
    )


def summarize_card(vc: ValidatedCard) -> str:
    """Human-readable card summary; only shows fields that are present.

    Output is console-safe (cp932 etc.): unmappable characters are replaced.
    """
    card = vc.card
    lines = [
        f"Agent name:        {card.name}",
        f"Description:       {card.description}",
        f"Agent version:     {card.version}",
    ]
    if card.HasField("provider"):
        lines.append(f"Provider:          {card.provider.organization}")
    for i in card.supported_interfaces:
        lines.append(f"Endpoint:          {i.url} ({i.protocol_binding}, protocol {i.protocol_version})")
    if card.default_input_modes:
        lines.append(f"Input modes:       {', '.join(card.default_input_modes)}")
    if card.default_output_modes:
        lines.append(f"Output modes:      {', '.join(card.default_output_modes)}")
    for s in card.skills:
        lines.append(f"Skill:             {s.id}: {s.name} - {s.description}")
    if card.security_schemes:
        lines.append(f"Auth schemes:      {', '.join(card.security_schemes)}")
    caps = [f.name for f, v in card.capabilities.ListFields() if v]
    if caps:
        lines.append(f"Capabilities:      {', '.join(caps)}")
    if card.documentation_url:
        lines.append(f"Documentation:     {card.documentation_url}")
    lines.append(f"Source URL:        {vc.source_url}")
    lines.append(f"Fetched at:        {vc.fetched_at.isoformat()}")
    # ponytail: ASCII sanitize for cp932-style consoles; the web UI shows full unicode
    return "\n".join(lines).encode("ascii", "replace").decode("ascii")
