"""Discover and inspect remote A2A agents.

Run: .venv\\Scripts\\python.exe discover.py <agent-card-url>
     .venv\\Scripts\\python.exe discover.py search <query>
"""
import sys

from directories.registry_provider import A2ARegistryProvider
from remote_agents.card_fetcher import CardFetchError, fetch_card_json
from remote_agents.card_validator import CardValidationError, summarize_card, validate_card
from remote_agents.endpoint_validator import check_endpoint
from remote_agents.url_safety import UnsafeUrlError


def discover(url: str) -> str:
    """Fetch + validate the card at `url`; return card summary + staged endpoint report."""
    vc = validate_card(fetch_card_json(url), url)
    return f"{summarize_card(vc)}\n\n{check_endpoint(vc).display()}"


def search(query: str) -> str:
    """Search a2aregistry.org; returns candidate listings (validate via their card URL)."""
    candidates = A2ARegistryProvider().search(query)
    if not candidates:
        return f"No agents matching {query!r}. Try the manual Agent Card URL instead."
    return "\n\n".join(c.display() for c in candidates)


if __name__ == "__main__":
    try:
        if len(sys.argv) >= 3 and sys.argv[1] == "search":
            print(search(" ".join(sys.argv[2:])))
        elif len(sys.argv) == 2:
            print(discover(sys.argv[1]))
        else:
            sys.exit("usage: python discover.py <agent-card-url> | search <query>")
    except (UnsafeUrlError, CardFetchError, CardValidationError) as exc:
        sys.exit(f"ERROR: {exc}")
