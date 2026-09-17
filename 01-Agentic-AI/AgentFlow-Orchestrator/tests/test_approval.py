"""Tests for the Policy Engine and Approval Manager.

Matches instruction.md section 20 (Tool Security), section 21 (Policy Engine),
and section 22 (Human-in-the-Loop).
"""

import asyncio

import pytest

from app.models.agent import AgentSpec
from app.policy.approval import (
    ApprovalAlreadyResolvedError,
    ApprovalManager,
    ApprovalNotFoundError,
    get_approval_manager,
)
from app.policy.engine import PolicyDecision, PolicyEngine, get_policy_engine


# --- Policy Engine Tests ---


class TestPolicyEngine:
    """Test the PolicyEngine permission checks."""

    def test_read_only_agent_no_approval(self):
        """Agent with only READ tools does not require approval."""
        engine = PolicyEngine()
        spec = AgentSpec(
            id="reader",
            name="Reader",
            goal="Read files",
            tools=["file_reader", "calculator"],
        )

        decision = engine.evaluate(spec)
        assert decision.allowed
        assert not decision.requires_approval

    def test_write_agent_no_approval(self):
        """Agent with WRITE tools does not require approval."""
        engine = PolicyEngine()
        spec = AgentSpec(
            id="writer",
            name="Writer",
            goal="Write files",
            tools=["file_reader", "file_writer", "python_executor"],
        )

        decision = engine.evaluate(spec)
        assert decision.allowed
        assert not decision.requires_approval

    def test_external_action_requires_approval(self):
        """Agent with EXTERNAL_ACTION tools requires approval."""
        engine = PolicyEngine()
        spec = AgentSpec(
            id="researcher",
            name="Researcher",
            goal="Search the web",
            tools=["web_search"],
        )

        decision = engine.evaluate(spec)
        assert not decision.allowed
        assert decision.requires_approval
        assert decision.approval_type == "tool"
        assert "web_search" in str(decision.approval_context)

    def test_http_request_requires_approval(self):
        """Agent with http_request tool requires approval."""
        engine = PolicyEngine()
        spec = AgentSpec(
            id="api_caller",
            name="API Caller",
            goal="Make HTTP requests",
            tools=["http_request"],
        )

        decision = engine.evaluate(spec)
        assert decision.requires_approval
        assert "http_request" in decision.reason

    def test_explicit_human_approval(self):
        """Agent with requires_human_approval=True always requires approval."""
        engine = PolicyEngine()
        spec = AgentSpec(
            id="sensitive",
            name="Sensitive Agent",
            goal="Do something sensitive",
            tools=["file_reader"],
            requires_human_approval=True,
        )

        decision = engine.evaluate(spec)
        assert decision.requires_approval
        assert decision.approval_type == "agent"

    def test_mixed_tools_requires_approval(self):
        """Agent with both READ and EXTERNAL_ACTION tools requires approval."""
        engine = PolicyEngine()
        spec = AgentSpec(
            id="mixed",
            name="Mixed Agent",
            goal="Read and search",
            tools=["file_reader", "web_search"],
        )

        decision = engine.evaluate(spec)
        assert decision.requires_approval

    def test_no_tools_no_approval(self):
        """Agent with no tools does not require approval."""
        engine = PolicyEngine()
        spec = AgentSpec(
            id="thinker",
            name="Thinker",
            goal="Think about things",
            tools=[],
        )

        decision = engine.evaluate(spec)
        assert decision.allowed
        assert not decision.requires_approval

    def test_singleton(self):
        """get_policy_engine returns a singleton."""
        e1 = get_policy_engine()
        e2 = get_policy_engine()
        assert e1 is e2


# --- Approval Manager Tests ---


class TestApprovalManager:
    """Test the ApprovalManager."""

    @pytest.mark.asyncio
    async def test_create_and_get_approval(self):
        """Create an approval and retrieve it."""
        manager = ApprovalManager()
        approval_id = await manager.create_request(
            execution_id="test-exec-1",
            approval_type="tool",
            context={"agent_id": "researcher", "tools": ["web_search"]},
            task_id="test-task-1",
        )

        approval = await manager.get_approval(approval_id)
        assert approval is not None
        assert approval["status"] == "pending"
        assert approval["approval_type"] == "tool"
        assert approval["context"]["agent_id"] == "researcher"

    @pytest.mark.asyncio
    async def test_approve(self):
        """Approve a pending approval."""
        manager = ApprovalManager()
        approval_id = await manager.create_request(
            execution_id="test-exec-2",
            approval_type="tool",
            context={"agent_id": "a1"},
        )

        result = await manager.approve(approval_id, user_id="test-user")
        assert result["status"] == "approved"
        assert result["user_id"] == "test-user"
        assert result["resolved_at"] is not None

        manager.cleanup(approval_id)

    @pytest.mark.asyncio
    async def test_reject(self):
        """Reject a pending approval."""
        manager = ApprovalManager()
        approval_id = await manager.create_request(
            execution_id="test-exec-3",
            approval_type="agent",
            context={"agent_id": "a2"},
        )

        result = await manager.reject(approval_id, user_id="test-user")
        assert result["status"] == "rejected"

        manager.cleanup(approval_id)

    @pytest.mark.asyncio
    async def test_approve_already_resolved(self):
        """Approving an already-resolved approval raises error."""
        manager = ApprovalManager()
        approval_id = await manager.create_request(
            execution_id="test-exec-4",
            approval_type="tool",
            context={},
        )

        await manager.approve(approval_id)
        with pytest.raises(ApprovalAlreadyResolvedError):
            await manager.approve(approval_id)

        manager.cleanup(approval_id)

    @pytest.mark.asyncio
    async def test_get_approval_not_found(self):
        """Getting a non-existent approval returns None."""
        manager = ApprovalManager()
        result = await manager.get_approval("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        """Approving a non-existent approval raises error."""
        manager = ApprovalManager()
        with pytest.raises(ApprovalNotFoundError):
            await manager.approve("nonexistent-id")

    @pytest.mark.asyncio
    async def test_list_pending(self):
        """List pending approvals."""
        manager = ApprovalManager()
        await manager.create_request(
            execution_id="test-exec-5",
            approval_type="tool",
            context={},
        )
        await manager.create_request(
            execution_id="test-exec-6",
            approval_type="agent",
            context={},
        )

        pending = await manager.list_pending()
        assert len(pending) >= 2

    @pytest.mark.asyncio
    async def test_list_pending_by_execution(self):
        """List pending approvals filtered by execution ID."""
        manager = ApprovalManager()
        await manager.create_request(
            execution_id="test-exec-filter",
            approval_type="tool",
            context={},
        )

        pending = await manager.list_pending(execution_id="test-exec-filter")
        assert len(pending) >= 1
        assert all(a["execution_id"] == "test-exec-filter" for a in pending)

    @pytest.mark.asyncio
    async def test_wait_for_approval_approved(self):
        """wait_for_approval returns 'approved' after approval."""
        manager = ApprovalManager()
        approval_id = await manager.create_request(
            execution_id="test-exec-wait",
            approval_type="tool",
            context={},
        )

        # Approve in a separate task after a short delay
        async def _delayed_approve():
            await asyncio.sleep(0.1)
            await manager.approve(approval_id)

        task = asyncio.create_task(_delayed_approve())
        decision = await manager.wait_for_approval(approval_id, timeout=5.0)
        await task

        assert decision == "approved"
        manager.cleanup(approval_id)

    @pytest.mark.asyncio
    async def test_wait_for_approval_rejected(self):
        """wait_for_approval returns 'rejected' after rejection."""
        manager = ApprovalManager()
        approval_id = await manager.create_request(
            execution_id="test-exec-wait-reject",
            approval_type="agent",
            context={},
        )

        async def _delayed_reject():
            await asyncio.sleep(0.1)
            await manager.reject(approval_id)

        task = asyncio.create_task(_delayed_reject())
        decision = await manager.wait_for_approval(approval_id, timeout=5.0)
        await task

        assert decision == "rejected"
        manager.cleanup(approval_id)