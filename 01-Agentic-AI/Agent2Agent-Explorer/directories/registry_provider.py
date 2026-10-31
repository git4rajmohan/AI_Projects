"""Adapter for the a2aregistry.org public API.

Verified 2026-10-31 by inspecting https://a2aregistry.org/api/ :
  GET /api/agents      -> {"agents": [{name, description, wellKnownURI, provider, skills, ...}]}
  GET /api/agents/{id} -> one agent object (same shape; used to resolve detail-page URLs)
No server-side search parameter is documented, so filtering is client-side.
"""
import re

import httpx

from directories.base import AgentCandidate, AgentDirectoryProvider
from remote_agents.card_fetcher import fetch_card_json

REGISTRY_URL = "https://a2aregistry.org/api/agents"
_AGENT_ID_IN_PAGE_URL = re.compile(r"/agents/([0-9a-f-]{36})/?$")


class A2ARegistryProvider(AgentDirectoryProvider):
    name = "a2aregistry.org"

    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self._transport = transport  # tests inject a mock; never hit the network in CI

    def search(self, query: str, skills: list[str] | None = None) -> list[AgentCandidate]:
        data = fetch_card_json(REGISTRY_URL, transport=self._transport)  # same SSRF/size/redirect guards
        query = query.lower().strip()
        wanted = {s.lower() for s in skills or []}
        results = []
        for entry in data.get("agents", []):
            card_url = entry.get("wellKnownURI") or ""
            if not card_url:
                continue
            skill_names = [s.get("name", "") for s in entry.get("skills", [])]
            skill_ids = [s.get("id", "") for s in entry.get("skills", [])]
            haystack = " ".join([entry.get("name", ""), entry.get("description", ""), *skill_names]).lower()
            if query and query not in haystack:
                continue
            if wanted and not wanted & {s.lower() for s in (*skill_ids, *skill_names)}:
                continue
            results.append(
                AgentCandidate(
                    name=entry.get("name", "?"),
                    description=entry.get("description", ""),
                    card_url=card_url,
                    provider=(entry.get("provider") or {}).get("organization", ""),
                    skills=skill_names,
                )
            )
        return results


def resolve_page_url(page_url: str) -> str | None:
    """registry.org/agents/<uuid>/ -> that agent's card URL, or None if not such a page."""
    match = _AGENT_ID_IN_PAGE_URL.search(page_url)
    if not match:
        return None
    try:
        # ponytail: sync httpx; one small GET on user action, not in a hot path
        entry = httpx.get(f"{REGISTRY_URL}/{match.group(1)}", timeout=30)
        entry.raise_for_status()
    except httpx.HTTPError:
        return None
    return entry.json().get("wellKnownURI") or None
