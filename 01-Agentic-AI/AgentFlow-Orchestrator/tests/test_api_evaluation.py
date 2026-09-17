"""Tests for the evaluation API endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.orchestrator.state import ExecutionState, get_state_manager


class TestEvaluationAPI:
    """Test the /api/executions/{id}/evaluation endpoint."""

    @pytest.mark.asyncio
    async def test_get_evaluation_not_found(self):
        """Getting evaluation for non-existent execution returns 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/executions/nonexistent-id/evaluation")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_evaluation_no_result(self):
        """Getting evaluation for execution without result returns 404."""
        # Create an execution with no result
        state_manager = get_state_manager()
        state = await state_manager.create_execution(
            task_id="test-task-eval",
            plan_id="test-plan-eval",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/executions/{state.execution_id}/evaluation")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_evaluation_with_result(self):
        """Getting evaluation for execution with evaluation result returns it."""
        # Create an execution and manually add evaluation result
        state_manager = get_state_manager()
        state = await state_manager.create_execution(
            task_id="test-task-eval2",
            plan_id="test-plan-eval2",
        )

        # Manually set result with evaluation
        state.result = {
            "outputs": {"a1": {"response": "done"}},
            "evaluation": {
                "success": True,
                "score": 0.85,
                "criteria": {"accuracy": 0.9, "completeness": 0.8},
                "issues": [],
                "recommendations": [],
            },
        }
        await state_manager.save_state(state)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/executions/{state.execution_id}/evaluation")

        assert response.status_code == 200
        data = response.json()
        assert data["evaluation"]["success"] is True
        assert data["evaluation"]["score"] == 0.85