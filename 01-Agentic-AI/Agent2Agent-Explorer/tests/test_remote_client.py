"""Remote client tests against the shared scripted A2A test server (see conftest.py).

ALLOW_LOCAL_AGENTS applies only here, via explicit allow_local=True.
"""
import pytest

from a2a.types import AgentCard

from remote_agents.card_validator import ValidatedCard
from remote_agents.remote_client import send_task
from tests.conftest import SCRIPTED_CARD


@pytest.mark.asyncio
async def test_completed_task(scripted_vc):
    result = await send_task(scripted_vc, "hello", allow_local=True, timeout=30)
    assert result.state == "COMPLETED"
    assert result.task_id
    assert result.context_id
    assert any("echo: hello" in t for t in result.texts)
    assert result.agent_name == "Test Agent"
    assert "Test Agent" in result.display()


@pytest.mark.asyncio
async def test_failed_task(scripted_vc):
    result = await send_task(scripted_vc, "please fail", allow_local=True, timeout=30)
    assert result.state == "FAILED"
    assert any("scripted failure" in t for t in result.texts)


@pytest.mark.asyncio
async def test_structured_result(scripted_vc):
    result = await send_task(scripted_vc, "give me data", allow_local=True, timeout=30)
    assert result.state == "COMPLETED"
    assert {"answer": 42.0} in [dict(d) for d in result.data]
    assert result.artifacts and result.artifacts[0]["name"] == "result-data"
    assert "not downloaded" in result.display()


@pytest.mark.asyncio
async def test_task_timeout(scripted_vc):
    result = await send_task(scripted_vc, "hang forever", allow_local=True, timeout=3)
    assert result.state == "TIMEOUT"


@pytest.mark.asyncio
async def test_private_endpoint_refused():
    bad = AgentCard()
    bad.CopyFrom(SCRIPTED_CARD)
    bad.supported_interfaces[0].url = "https://10.0.0.5/a2a"
    from remote_agents.url_safety import UnsafeUrlError

    with pytest.raises(UnsafeUrlError):
        await send_task(ValidatedCard(card=bad, source_url="x"), "hi", allow_local=True)
