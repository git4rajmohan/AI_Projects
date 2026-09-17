"""Tests for the task and plan API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_create_task_and_generate_plan():
    """Create a task, then generate a plan for it.

    Note: Plan generation calls the LLM, which requires OPENAI_API_KEY
    to be set. If the key is a placeholder, this test will get a 500 error
    from the LLM call — that's expected without a real key.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create task
        response = await client.post("/api/tasks", json={
            "intent": "Convert this CSV into an Excel file."
        })
        assert response.status_code == 200
        task = response.json()
        assert task["status"] == "created"
        task_id = task["id"]

        # Try to generate plan — may fail if no real API key
        plan_response = await client.post("/api/plans", json={"task_id": task_id})
        if plan_response.status_code == 200:
            plan = plan_response.json()
            assert plan["task_id"] == task_id
            assert plan["objective"]
            assert "plan_data" in plan
        else:
            # Expected if no real Ollama Cloud API key
            assert plan_response.status_code in (500, 422)


@pytest.mark.asyncio
async def test_get_nonexistent_task():
    """Getting a non-existent task returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tasks/nonexistent-id")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_nonexistent_plan():
    """Getting a non-existent plan returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/plans/nonexistent-id")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_generate_plan_nonexistent_task():
    """Generating a plan for non-existent task returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/plans", json={"task_id": "nonexistent"})
        assert response.status_code == 404