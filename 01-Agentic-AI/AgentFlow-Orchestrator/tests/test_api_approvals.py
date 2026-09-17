"""Tests for the approvals API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.policy.approval import get_approval_manager


async def _create_approval(execution_id: str = "test-exec-api") -> str:
    """Helper: create an approval via the manager and return its ID."""
    manager = get_approval_manager()
    approval_id = await manager.create_request(
        execution_id=execution_id,
        approval_type="tool",
        context={"agent_id": "test_agent", "tools": ["web_search"]},
        task_id="test-task-api",
    )
    return approval_id


class TestApprovalsAPI:
    """Test the /api/approvals endpoints."""

    @pytest.mark.asyncio
    async def test_list_approvals(self):
        """GET /api/approvals returns pending approvals."""
        await _create_approval("test-exec-list")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/approvals")

        assert response.status_code == 200
        data = response.json()
        assert "approvals" in data
        assert data["count"] >= 1

    @pytest.mark.asyncio
    async def test_get_approval(self):
        """GET /api/approvals/{id} returns approval details."""
        approval_id = await _create_approval("test-exec-get")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/approvals/{approval_id}")

        assert response.status_code == 200
        approval = response.json()
        assert approval["id"] == approval_id
        assert approval["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_approval_not_found(self):
        """GET /api/approvals/{id} returns 404 for unknown approval."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/approvals/nonexistent-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_request(self):
        """POST /api/approvals/{id}/approve approves a request."""
        approval_id = await _create_approval("test-exec-approve")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/approvals/{approval_id}/approve",
                json={"user_id": "api-tester"},
            )

        assert response.status_code == 200
        approval = response.json()
        assert approval["status"] == "approved"
        assert approval["user_id"] == "api-tester"

    @pytest.mark.asyncio
    async def test_reject_request(self):
        """POST /api/approvals/{id}/reject rejects a request."""
        approval_id = await _create_approval("test-exec-reject")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/approvals/{approval_id}/reject",
                json={"user_id": "api-tester"},
            )

        assert response.status_code == 200
        approval = response.json()
        assert approval["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        """POST /api/approvals/{id}/approve returns 404 for unknown approval."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/approvals/nonexistent-id/approve",
                json={"user_id": "test"},
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_already_resolved(self):
        """POST /api/approvals/{id}/approve returns 400 for already-resolved approval."""
        approval_id = await _create_approval("test-exec-resolved")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First approve succeeds
            response1 = await client.post(
                f"/api/approvals/{approval_id}/approve",
                json={"user_id": "user1"},
            )
            assert response1.status_code == 200

            # Second approve fails — already resolved
            response2 = await client.post(
                f"/api/approvals/{approval_id}/approve",
                json={"user_id": "user2"},
            )
            assert response2.status_code == 400