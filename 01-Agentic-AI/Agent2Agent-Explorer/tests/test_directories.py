"""Directory provider tests: mocked registry responses, zero network."""
import json
import socket

import httpx
import pytest

from directories.manual_url import ManualUrlProvider
from directories.registry_provider import A2ARegistryProvider

REGISTRY_PAYLOAD = {
    "agents": [
        {
            "name": "Research Agent",
            "description": "Performs deep research tasks",
            "wellKnownURI": "https://research.example/.well-known/agent-card.json",
            "provider": {"organization": "Example Org"},
            "skills": [{"id": "web-research", "name": "Web Research"}],
        },
        {
            "name": "Chess Agent",
            "description": "Plays chess",
            "wellKnownURI": "https://chess.example/.well-known/agent-card.json",
            "provider": {"organization": "Chess Inc"},
            "skills": [{"id": "play-chess", "name": "Play Chess"}],
        },
        {
            "name": "No Card Agent",
            "description": "broken listing",
            "wellKnownURI": "",
            "skills": [],
        },
    ]
}


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


@pytest.fixture
def registry():
    t = httpx.MockTransport(lambda req: httpx.Response(200, json=REGISTRY_PAYLOAD))
    return A2ARegistryProvider(transport=t)


def test_manual_provider_returns_candidate():
    results = ManualUrlProvider().search("https://agent.example/.well-known/agent-card.json")
    assert len(results) == 1
    assert results[0].card_url == "https://agent.example/.well-known/agent-card.json"


def test_manual_provider_rejects_non_url():
    assert ManualUrlProvider().search("not a url") == []
    assert ManualUrlProvider().search("ftp://agent.example/card") == []


def test_registry_search_by_text(registry):
    results = registry.search("research")
    assert [c.name for c in results] == ["Research Agent"]
    assert results[0].card_url == "https://research.example/.well-known/agent-card.json"
    assert results[0].provider == "Example Org"
    assert results[0].skills == ["Web Research"]


def test_registry_search_by_skill(registry):
    results = registry.search("", skills=["play-chess"])
    assert [c.name for c in results] == ["Chess Agent"]


def test_registry_empty_query_lists_all_with_cards(registry):
    # entries without a card URL are dropped
    assert [c.name for c in registry.search("")] == ["Research Agent", "Chess Agent"]


def test_registry_no_match(registry):
    assert registry.search("quantum basket weaving") == []


def test_resolve_page_url(monkeypatch):
    import directories.registry_provider as rp

    captured = {}

    def fake_get(url, timeout):
        captured["url"] = url

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"name": "WB", "wellKnownURI": "https://wb.example/.well-known/agent.json"}

        return Resp()

    monkeypatch.setattr(rp.httpx, "get", fake_get)
    result = rp.resolve_page_url("https://a2aregistry.org/agents/7d13b816-7f2a-4eb3-9736-1914fef5eae4/")
    assert result == "https://wb.example/.well-known/agent.json"
    assert captured["url"].endswith("/api/agents/7d13b816-7f2a-4eb3-9736-1914fef5eae4")


def test_resolve_page_url_ignores_non_page(monkeypatch):
    from directories.registry_provider import resolve_page_url

    assert resolve_page_url("https://a2aregistry.org/api/agents") is None
    assert resolve_page_url("https://some-other-agents-site.org/agents/deadbeef/") is None


def test_registry_candidate_display(registry):
    text = registry.search("research")[0].display()
    assert "Research Agent" in text and "card: https://research.example" in text
