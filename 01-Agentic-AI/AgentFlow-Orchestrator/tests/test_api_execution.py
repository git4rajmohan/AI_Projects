"""Tests for the execution API routes.

Matches instruction.md section 15-17 (Orchestration, State, Events).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class TestExecutionAPI:
    """Test the /api/executions endpoints."""

    @pytest.mark.asyncio
    async def test_start_execution_plan_not_found(self):
        """Starting execution with non-existent plan returns 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/executions",
                json={"plan_id": "nonexistent-plan"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_execution_not_found(self):
        """Getting a non-existent execution returns 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/executions/nonexistent-id")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_events_not_found(self):
        """Getting events for non-existent execution returns 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/executions/nonexistent-id/events")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_not_found(self):
        """Cancelling a non-existent execution returns 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/executions/nonexistent-id/cancel")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_start_execution_not_approved(self):
        """Starting execution with a non-approved plan returns 400."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create a task first
            task_resp = await client.post(
                "/api/tasks",
                json={"intent": "Test task"},
            )
            task_id = task_resp.json()["id"]

            # Create a plan directly in DB (status='created', not 'approved')
            from sqlalchemy import select
            from app.db.database import async_session_factory
            from app.models.plan import PlanModel

            plan = PlanModel(
                id="test-plan-unapproved",
                task_id=task_id,
                objective="Test",
                plan_data={
                    "task_id": task_id,
                    "objective": "Test",
                    "agents": [],
                },
                status="created",
            )
            async with async_session_factory() as session:
                session.add(plan)
                await session.commit()

            # Try to execute — should fail with 400
            response = await client.post(
                "/api/executions",
                json={"plan_id": "test-plan-unapproved"},
            )
        assert response.status_code == 400
        assert "approved" in response.json()["detail"]