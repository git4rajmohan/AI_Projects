"""Always-available fallback: the user supplies an Agent Card URL directly."""
from urllib.parse import urlparse

from directories.base import AgentCandidate, AgentDirectoryProvider


class ManualUrlProvider(AgentDirectoryProvider):
    """Treats the query as an Agent Card URL supplied by an external developer."""

    name = "manual"

    def search(self, query: str, skills: list[str] | None = None) -> list[AgentCandidate]:
        parsed = urlparse(query.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return []
        return [AgentCandidate(name=parsed.hostname, description="manually entered Agent Card URL",
                               card_url=query.strip())]
