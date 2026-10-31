"""SQLite persistence for saved remote agents and task history.

Stores metadata only — never bearer tokens or any credential material
(schema per instructions §17).
"""
import json
import sqlite3
from datetime import datetime, timezone

from remote_agents.card_validator import ValidatedCard
from remote_agents.remote_client import TaskResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS remote_agents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    agent_card_url TEXT NOT NULL UNIQUE,
    service_endpoint TEXT,
    protocol_version TEXT,
    provider_name TEXT,
    skills_json TEXT,
    auth_scheme TEXT,
    trusted INTEGER NOT NULL DEFAULT 0,
    last_validated_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_task_history (
    id INTEGER PRIMARY KEY,
    remote_agent_id INTEGER NOT NULL REFERENCES remote_agents(id),
    task_id TEXT,
    context_id TEXT,
    task_text TEXT,
    task_state TEXT,
    result_summary TEXT,
    submitted_at TEXT,
    completed_at TEXT,
    error_message TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentStore:
    """Thin sqlite3 wrapper; one connection, dict rows."""

    def __init__(self, path: str = "agents.db"):
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def save_agent(self, vc: ValidatedCard, *, trusted: bool | None = None) -> int:
        """Insert or refresh (by agent_card_url) from a validated card. Returns agent id."""
        card = vc.card
        iface = next((i for i in card.supported_interfaces if i.url), None)
        skills = json.dumps(
            [{"id": s.id, "name": s.name, "description": s.description} for s in card.skills]
        )
        row = {
            "name": card.name,
            "description": card.description,
            "agent_card_url": vc.source_url,
            "service_endpoint": iface.url if iface else None,
            "protocol_version": iface.protocol_version if iface else None,
            "provider_name": card.provider.organization if card.HasField("provider") else None,
            "skills_json": skills,
            "auth_scheme": ", ".join(card.security_schemes),
            "last_validated_at": vc.fetched_at.isoformat(),
            "created_at": _now(),
        }
        with self._db:
            self._db.execute(
                """INSERT INTO remote_agents
                   (name, description, agent_card_url, service_endpoint, protocol_version,
                    provider_name, skills_json, auth_scheme, last_validated_at, created_at)
                   VALUES (:name, :description, :agent_card_url, :service_endpoint, :protocol_version,
                           :provider_name, :skills_json, :auth_scheme, :last_validated_at, :created_at)
                   ON CONFLICT(agent_card_url) DO UPDATE SET
                       name=excluded.name, description=excluded.description,
                       service_endpoint=excluded.service_endpoint,
                       protocol_version=excluded.protocol_version,
                       provider_name=excluded.provider_name, skills_json=excluded.skills_json,
                       auth_scheme=excluded.auth_scheme,
                       last_validated_at=excluded.last_validated_at""",
                row,
            )
            agent_id = self._db.execute(
                "SELECT id FROM remote_agents WHERE agent_card_url = ?", (vc.source_url,)
            ).fetchone()["id"]
            if trusted is not None:
                self._db.execute("UPDATE remote_agents SET trusted = ? WHERE id = ?", (int(trusted), agent_id))
        return agent_id

    def get_agent(self, agent_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM remote_agents WHERE id = ?", (agent_id,)).fetchone()
        return dict(row) if row else None

    def list_agents(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM remote_agents ORDER BY name")]

    def set_trusted(self, agent_id: int, trusted: bool) -> None:
        with self._db:
            self._db.execute("UPDATE remote_agents SET trusted = ? WHERE id = ?", (int(trusted), agent_id))

    def delete_agent(self, agent_id: int) -> bool:
        """Remove a saved agent and its task history. True if it existed."""
        with self._db:
            self._db.execute("DELETE FROM agent_task_history WHERE remote_agent_id = ?", (agent_id,))
            cursor = self._db.execute("DELETE FROM remote_agents WHERE id = ?", (agent_id,))
            return cursor.rowcount > 0

    def record_task(
        self,
        agent_id: int,
        task_text: str,
        result: TaskResult,
        *,
        submitted_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        summary = result.texts[0][:500] if result.texts else None
        with self._db:
            self._db.execute(
                """INSERT INTO agent_task_history
                   (remote_agent_id, task_id, context_id, task_text, task_state,
                    result_summary, submitted_at, completed_at, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_id, result.task_id, result.context_id, task_text, result.state,
                 summary, submitted_at or _now(), _now(), error_message),
            )

    def task_history(self, agent_id: int) -> list[dict]:
        return [
            dict(r)
            for r in self._db.execute(
                "SELECT * FROM agent_task_history WHERE remote_agent_id = ? ORDER BY id DESC", (agent_id,)
            )
        ]
