"""Directory provider interface for discovering remote A2A agents."""
from dataclasses import dataclass, field


@dataclass
class AgentCandidate:
    """A discovery lead: metadata + card URL. Not validated until the card is fetched."""

    name: str
    description: str
    card_url: str
    provider: str = ""
    skills: list[str] = field(default_factory=list)

    def display(self) -> str:
        skills = ", ".join(self.skills) or "-"
        return f"{self.name} ({self.provider or 'unknown provider'})\n  skills: {skills}\n  card: {self.card_url}"


class AgentDirectoryProvider:
    """Searchable source of agent candidates."""

    name = "base"

    def search(self, query: str, skills: list[str] | None = None) -> list[AgentCandidate]:
        raise NotImplementedError
