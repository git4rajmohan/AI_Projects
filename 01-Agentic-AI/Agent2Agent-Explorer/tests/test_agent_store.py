"""Agent store tests: tmp-file SQLite, no network."""
import pytest

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentProvider, AgentSkill

from remote_agents.agent_store import AgentStore
from remote_agents.card_validator import ValidatedCard
from remote_agents.remote_client import TaskResult

URL = "https://agent.example/.well-known/agent-card.json"


def make_vc(name="Research Agent", url=URL) -> ValidatedCard:
    card = AgentCard(
        name=name,
        description="does research",
        version="1.0.0",
        provider=AgentProvider(organization="Example Org"),
        supported_interfaces=[
            AgentInterface(url="https://agent.example/a2a", protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[AgentSkill(id="research", name="Research", description="researches", tags=["r"])],
    )
    return ValidatedCard(card=card, source_url=url)


@pytest.fixture
def store(tmp_path):
    s = AgentStore(str(tmp_path / "agents.db"))
    yield s
    s.close()


def test_save_and_reload(store, tmp_path):
    agent_id = store.save_agent(make_vc())
    # reopen = "restart the application"
    store.close()
    reopened = AgentStore(str(tmp_path / "agents.db"))
    agent = reopened.get_agent(agent_id)
    assert agent["name"] == "Research Agent"
    assert agent["agent_card_url"] == URL
    assert agent["service_endpoint"] == "https://agent.example/a2a"
    assert agent["provider_name"] == "Example Org"
    assert "research" in agent["skills_json"]
    assert agent["trusted"] == 0
    assert agent["last_validated_at"]
    reopened.close()


def test_duplicate_url_updates_not_duplicates(store):
    id1 = store.save_agent(make_vc(name="Old Name"))
    store.save_agent(make_vc(name="Other Agent", url="https://other.example/card.json"))
    id2 = store.save_agent(make_vc(name="New Name"))  # same URL -> refresh, correct id back
    assert id1 == id2
    agents = store.list_agents()
    assert len(agents) == 2
    assert store.get_agent(id1)["name"] == "New Name"


def test_trusted_flag(store):
    agent_id = store.save_agent(make_vc())
    store.set_trusted(agent_id, True)
    assert store.get_agent(agent_id)["trusted"] == 1
    store.set_trusted(agent_id, False)
    assert store.get_agent(agent_id)["trusted"] == 0


def test_task_history(store):
    agent_id = store.save_agent(make_vc())
    result = TaskResult(agent_name="Research Agent", state="COMPLETED", task_id="t-1",
                        context_id="c-1", texts=["the answer"])
    store.record_task(agent_id, "research playwright", result)
    history = store.task_history(agent_id)
    assert len(history) == 1
    h = history[0]
    assert h["task_id"] == "t-1"
    assert h["task_state"] == "COMPLETED"
    assert h["result_summary"] == "the answer"
    assert h["submitted_at"] and h["completed_at"]


def test_no_credential_columns(store):
    for table in ("remote_agents", "agent_task_history"):
        cols = [r["name"].lower() for r in store._db.execute(f"PRAGMA table_info({table})")]
        assert not any("token" in c or "secret" in c or "password" in c for c in cols)


def test_delete_agent_removes_history(store):
    agent_id = store.save_agent(make_vc())
    result = TaskResult(agent_name="Research Agent", state="COMPLETED", task_id="t-9", texts=["x"])
    store.record_task(agent_id, "task text", result)
    assert store.delete_agent(agent_id) is True
    assert store.get_agent(agent_id) is None
    assert agent_id not in [a["id"] for a in store.list_agents()]
    # deleting an unknown id reports not-found
    assert store.delete_agent(agent_id) is False
