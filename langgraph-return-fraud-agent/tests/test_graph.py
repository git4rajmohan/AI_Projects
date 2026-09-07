"""Tests for app.graph — Phase 3 & 4 verification.

Phase 3: graph structure & deterministic happy paths (no checkpointer).
Phase 4: interrupt()-based photo loop, human-approval gate, and durable
SQLite-checkpointed persistence across graph instances.
"""
import uuid
from pathlib import Path

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app import graph as graph_module
from app.graph import (
    build_graph,
    classify_condition_stub,
    graph,
    make_sqlite_saver,
    thread_config,
)
from app.schemas import ItemCondition, ReturnStatus


@pytest.fixture(autouse=True)
def stub_llm_classifier(monkeypatch):
    """Graph tests must be deterministic: use the keyword stub, not the LLM."""
    monkeypatch.setattr(graph_module.llm, "classify_reason", classify_condition_stub)
    monkeypatch.setattr(
        graph_module.llm,
        "classify_reason_with_source",
        lambda reason: (classify_condition_stub(reason), "llm"),
    )


# ---------------------------------------------------------------------------
# Stub classifier
# ---------------------------------------------------------------------------
class TestClassifyConditionStub:
    @pytest.mark.parametrize(
        ("reason", "expected"),
        [
            ("Item arrived broken", ItemCondition.damaged_defective),
            ("Screen is cracked", ItemCondition.damaged_defective),
            ("There is a defect in the hinge", ItemCondition.damaged_defective),
            ("The device is not working", ItemCondition.damaged_defective),
            ("Stopped working after a week", ItemCondition.damaged_defective),
            ("It's a DOA unit", ItemCondition.damaged_defective),
            ("I just don't like the color anymore", ItemCondition.buyer_remorse),
            ("Ordered the wrong size", ItemCondition.buyer_remorse),
            ("", ItemCondition.buyer_remorse),
        ],
    )
    def test_keyword_table(self, reason, expected):
        assert classify_condition_stub(reason) is expected

    def test_case_insensitive(self):
        assert classify_condition_stub("IT IS BROKEN") is ItemCondition.damaged_defective


# ---------------------------------------------------------------------------
# Happy-path graph invocations (no checkpointer, plain invoke)
# ---------------------------------------------------------------------------
def make_state(**overrides):
    """Build a minimal valid ReturnState payload for graph invocation."""
    base = {
        "order_id": "ORD-1002",  # fresh, $129.50, CUST-B (clean history)
        "item_id": "SKU-HEADPHN-02",
        "reason_text": "I just don't like them anymore",
        "photo_provided": False,
    }
    base.update(overrides)
    return base


class TestGraphHappyPaths:
    def test_damaged_with_photo_completes(self):
        """Damaged claim + photo → fee $0.00 → completed with full refund."""
        result = graph.invoke(
            make_state(
                order_id="ORD-1002",
                item_id="SKU-HEADPHN-02",
                reason_text="Headphones arrived broken",
                photo_provided=True,
            )
        )
        assert result["status"] == ReturnStatus.completed
        assert result["item_condition"] == ItemCondition.damaged_defective
        assert result["shipping_fee"] == 0.00
        assert result["refund_amount"] == 129.50
        assert result["fraud_score"] == 0.0
        assert result["fraud_flags"] == []

    def test_buyers_remorse_charges_fee(self):
        """Buyer's remorse → $5.99 fee deducted from refund."""
        result = graph.invoke(
            make_state(
                reason_text="Changed my mind, ordered the wrong model",
                photo_provided=False,
            )
        )
        assert result["status"] == ReturnStatus.completed
        assert result["item_condition"] == ItemCondition.buyer_remorse
        assert result["shipping_fee"] == 5.99
        assert result["refund_amount"] == pytest.approx(123.51)

    def test_policy_denial_old_order(self):
        """Order older than 30 days → denied_policy, fee/refund never computed.

        LangGraph returns only keys that nodes actually updated, so unset
        defaults (shipping_fee/refund_amount) are absent from the output dict.
        """
        result = graph.invoke(
            make_state(
                order_id="ORD-1003",  # 45 days old
                item_id="SKU-KEYBOARD-03",
                reason_text="Stopped working",
                photo_provided=True,
            )
        )
        assert result["status"] == ReturnStatus.denied_policy
        assert result["item_value"] == 79.99
        assert "shipping_fee" not in result  # calculate_fee_node never ran
        assert "refund_amount" not in result  # fraud_check_node never ran
        assert any(
            "return window" in line for line in result["decision_log"]
        )

    def test_policy_denial_unknown_order(self):
        result = graph.invoke(make_state(order_id="ORD-UNKNOWN"))
        assert result["status"] == ReturnStatus.denied_policy

    def test_decision_log_records_journey(self):
        """Audit trail must record every node the happy path visits."""
        result = graph.invoke(make_state(reason_text="Just changed my mind"))
        log_text = "\n".join(result["decision_log"])
        for expected in ("validated", "classified as", "shipping fee", "fraud score", "refund"):
            assert expected in log_text, f"missing '{expected}' in decision log"

    def test_graph_singleton_is_compiled(self):
        """Module-level graph is a compiled instance, not a builder."""
        from langgraph.graph.state import CompiledStateGraph

        assert isinstance(graph, CompiledStateGraph)
        # Node topology matches the plan (9 nodes wired in Phase 4).
        assert set(graph.get_graph().nodes) == {
            "__start__",
            "__end__",
            "validate_policy",
            "classify_condition",
            "check_photo_proof",
            "calculate_fee",
            "fraud_check",
            "human_gate",
            "finalize_refund",
            "reject_policy",
            "reject_by_manager",
        }


class TestGraphRouting:
    def test_high_value_routes_to_human_gate(self):
        """Refund > $200 must pause at human_gate (Phase 3 placeholder)."""
        result = graph.invoke(
            make_state(
                order_id="ORD-1001",  # $899 laptop, fresh
                item_id="SKU-LAPTOP-01",
                reason_text="Just don't want it",
                photo_provided=False,
            )
        )
        assert result["status"] == ReturnStatus.awaiting_approval
        assert result["refund_amount"] == pytest.approx(893.01)  # 899 - 5.99 remorse fee

    def test_fraud_velocity_routes_to_human_gate(self):
        """CUST-A has 3 returns in 30 days → velocity flag → human gate."""
        result = graph.invoke(
            make_state(
                order_id="ORD-1004",  # $349 monitor, CUST-A
                item_id="SKU-MONITOR-04",
                reason_text="Just don't want it",
                photo_provided=False,
            )
        )
        assert result["fraud_score"] == pytest.approx(0.4)
        assert "high_return_velocity" in result["fraud_flags"]
        assert result["status"] == ReturnStatus.awaiting_approval

    def test_damaged_without_photo_pauses_for_proof(self):
        """Damaged claim with no photo → awaiting_photo pause (Phase 3)."""
        result = graph.invoke(
            make_state(
                order_id="ORD-1002",
                item_id="SKU-HEADPHN-02",
                reason_text="Headphones are broken",
                photo_provided=False,
            )
        )
        assert result["status"] == ReturnStatus.awaiting_photo
        # Fee/fraud stages must not have run yet (keys absent from output dict)
        assert "shipping_fee" not in result
        assert "refund_amount" not in result


# ---------------------------------------------------------------------------
# Phase 4 — interrupts, cyclical loop, SQLite checkpointer
# ---------------------------------------------------------------------------
DAMAGED_NO_PHOTO = {
    "order_id": "ORD-1002",   # fresh, $129.50, clean history
    "item_id": "SKU-HEADPHN-02",
    "reason_text": "Headphones arrived broken",
    "photo_provided": False,
}
HIGH_VALUE = {
    "order_id": "ORD-1001",   # fresh, $899.00, CUST-A
    "item_id": "SKU-LAPTOP-01",
    "reason_text": "Just don't want it",
    "photo_provided": False,
}


def paused_interrupt(result: dict) -> dict:
    """Extract the pending interrupt payload from a paused invoke result."""
    interrupts = result.get("__interrupt__")
    assert interrupts, f"expected graph to pause with __interrupt__, got: {result}"
    return interrupts[0].value


class TestPhotoLoopInterrupts:
    """Photo-proof cyclical loop via interrupt() with a SQLite checkpointer."""

    @pytest.fixture()
    def app(self, tmp_path: Path):
        return build_graph(make_sqlite_saver(str(tmp_path / "cp.sqlite")))

    def test_pause_presents_photo_required_interrupt(self, app, tmp_path):
        tid = str(uuid.uuid4())
        result = app.invoke(DAMAGED_NO_PHOTO, thread_config(tid))
        assert result["status"] == ReturnStatus.awaiting_photo
        payload = paused_interrupt(result)
        assert payload["reason"] == "photo_required"
        assert payload["order_id"] == "ORD-1002"
        assert payload["attempt"] == 1
        assert payload["max_attempts"] == 3

        # Checkpointed state exposes the pause
        snap = app.get_state(thread_config(tid))
        assert snap.next == ("check_photo_proof",)
        assert snap.values["status"] == ReturnStatus.awaiting_photo

    def test_resume_with_photo_completes(self, app):
        tid = str(uuid.uuid4())
        app.invoke(DAMAGED_NO_PHOTO, thread_config(tid))
        result = app.invoke(
            Command(resume={"photo_provided": True, "photo_url": "http://x/p.jpg"}),
            thread_config(tid),
        )
        assert result["status"] == ReturnStatus.completed
        assert result["photo_provided"] is True
        assert result["photo_retry_count"] == 1
        assert result["shipping_fee"] == 0.00      # damaged → no fee
        assert result["refund_amount"] == 129.50
        assert result["fraud_flags"] == []

    def test_resume_without_photo_loops_back(self, app):
        """Resuming with photo_provided=False re-interrupts, bounded by retries."""
        tid = str(uuid.uuid4())
        app.invoke(DAMAGED_NO_PHOTO, thread_config(tid))
        result = app.invoke(
            Command(resume={"photo_provided": False}),
            thread_config(tid),
        )
        assert result["status"] == ReturnStatus.awaiting_photo  # still paused
        payload = paused_interrupt(result)
        assert payload["attempt"] == 2

        snap = app.get_state(thread_config(tid))
        assert snap.values["photo_retry_count"] == 1
        assert snap.values["status"] == ReturnStatus.awaiting_photo

    def test_retry_exhaustion_proceeds_and_fraud_flags(self, app):
        """MAX_PHOTO_RETRIES exhausted → proceed; fraud gate catches the claim."""
        tid = str(uuid.uuid4())
        app.invoke(DAMAGED_NO_PHOTO, thread_config(tid))
        # Attempts 1..3 all fail to provide a photo (retry_count: 1, 2, 3)
        for attempt in (1, 2, 3):
            result = app.invoke(
                Command(resume={"photo_provided": False}), thread_config(tid)
            )
            if attempt < 3:
                assert result["status"] == ReturnStatus.awaiting_photo
                assert paused_interrupt(result)["attempt"] == attempt + 1
            else:
                # 3rd failed resume → retry_count hits MAX → loop exits →
                # calculate_fee → fraud_check (no_photo_proof flag) → human_gate
                assert result["status"] == ReturnStatus.awaiting_approval
        assert "no_photo_proof" in result["fraud_flags"]
        assert result["photo_retry_count"] == 3

    def test_retry_exhaustion_fraud_score_matches_plan_weights(self, app):
        """Exhausted damaged claim: no_photo_proof (0.4) only → score 0.4."""
        tid = str(uuid.uuid4())
        app.invoke(DAMAGED_NO_PHOTO, thread_config(tid))
        for _ in range(3):
            result = app.invoke(
                Command(resume={"photo_provided": False}), thread_config(tid)
            )
        assert result["fraud_score"] == pytest.approx(0.4)
        assert result["status"] == ReturnStatus.awaiting_approval

    def test_buyer_remorse_never_enters_photo_loop(self, app):
        tid = str(uuid.uuid4())
        result = app.invoke(
            {
                "order_id": "ORD-1002",
                "item_id": "SKU-HEADPHN-02",
                "reason_text": "Changed my mind",
                "photo_provided": False,
            },
            thread_config(tid),
        )
        assert result["status"] == ReturnStatus.completed
        assert "__interrupt__" not in result
        assert result["shipping_fee"] == pytest.approx(5.99)

    def test_interrupt_without_checkpointer_surfaces_in_result(self):
        """No checkpointer: interrupt surfaces as __interrupt__ in the result."""
        result = graph.invoke(DAMAGED_NO_PHOTO)
        assert result["status"] == ReturnStatus.awaiting_photo
        payload = paused_interrupt(result)
        assert payload["reason"] == "photo_required"


class TestHumanGateInterrupt:
    @pytest.fixture()
    def app(self, tmp_path: Path):
        return build_graph(make_sqlite_saver(str(tmp_path / "cp.sqlite")))

    def test_pause_presents_manager_approval_interrupt(self, app):
        tid = str(uuid.uuid4())
        result = app.invoke(HIGH_VALUE, thread_config(tid))
        assert result["status"] == ReturnStatus.awaiting_approval
        payload = paused_interrupt(result)
        assert payload["reason"] == "manager_approval_required"
        assert payload["refund_amount"] == pytest.approx(893.01)  # 899 - 5.99
        assert payload["order_id"] == "ORD-1001"

        snap = app.get_state(thread_config(tid))
        assert snap.next == ("human_gate",)

    def test_approve_resumes_to_completed(self, app):
        tid = str(uuid.uuid4())
        app.invoke(HIGH_VALUE, thread_config(tid))
        result = app.invoke(
            Command(resume={"decision": "approve", "manager_note": "ok"}),
            thread_config(tid),
        )
        assert result["status"] == ReturnStatus.completed
        assert result["manager_note"] == "ok"
        assert result["refund_amount"] == pytest.approx(893.01)

    def test_reject_resumes_to_rejected(self, app):
        tid = str(uuid.uuid4())
        app.invoke(HIGH_VALUE, thread_config(tid))
        result = app.invoke(
            Command(resume={"decision": "reject", "manager_note": "suspicious"}),
            thread_config(tid),
        )
        assert result["status"] == ReturnStatus.rejected
        assert result["manager_note"] == "suspicious"
        # refund never processed
        assert "refund_amount" in result  # fraud node computed it
        log = "\n".join(result["decision_log"])
        assert "processed successfully" not in log

    def test_unrecognized_decision_fails_closed(self, app):
        tid = str(uuid.uuid4())
        app.invoke(HIGH_VALUE, thread_config(tid))
        result = app.invoke(
            Command(resume={"decision": "maybe"}), thread_config(tid)
        )
        assert result["status"] == ReturnStatus.rejected
        assert any(
            "unrecognized manager decision" in line
            for line in result["decision_log"]
        )

    def test_fraud_velocity_gate_pauses_and_approves(self, app):
        """CUST-A velocity flag (0.4) alone crosses the 0.7 threshold? No —
        0.4 < 0.7, but the plan gates on flags via no_photo_proof only;
        velocity alone finalizes. Verify the actual routing."""
        tid = str(uuid.uuid4())
        result = app.invoke(
            {
                "order_id": "ORD-1004",  # $349, CUST-A (velocity flag)
                "item_id": "SKU-MONITOR-04",
                "reason_text": "Just don't want it",
                "photo_provided": False,
            },
            thread_config(tid),
        )
        # Velocity (0.4) < threshold (0.7) and value $349 > $200 → gate by value
        assert result["status"] == ReturnStatus.awaiting_approval
        result2 = app.invoke(
            Command(resume={"decision": "approve"}), thread_config(tid)
        )
        assert result2["status"] == ReturnStatus.completed
        assert result2["fraud_score"] == pytest.approx(0.4)
        assert "high_return_velocity" in result2["fraud_flags"]


class TestSQLitePersistence:
    """Durable checkpointing: a fresh graph instance resumes the same thread."""

    @pytest.fixture()
    def db_path(self, tmp_path: Path):
        return str(tmp_path / "persist.sqlite")

    def test_new_graph_instance_resumes_paused_thread(self, db_path):
        """Phase 4 persistence mandate: pause → new graph → resume succeeds."""
        tid = str(uuid.uuid4())
        app1 = build_graph(make_sqlite_saver(db_path))
        app1.invoke(DAMAGED_NO_PHOTO, thread_config(tid))
        assert app1.get_state(thread_config(tid)).next == ("check_photo_proof",)

        # Fresh instance (simulates a server restart) on the same sqlite file
        app2 = build_graph(make_sqlite_saver(db_path))
        snap = app2.get_state(thread_config(tid))
        assert snap.next == ("check_photo_proof",)
        assert snap.values["status"] == ReturnStatus.awaiting_photo

        result = app2.invoke(
            Command(resume={"photo_provided": True}), thread_config(tid)
        )
        assert result["status"] == ReturnStatus.completed
        assert result["refund_amount"] == pytest.approx(129.50)

    def test_new_graph_instance_resumes_manager_gate(self, db_path):
        tid = str(uuid.uuid4())
        app1 = build_graph(make_sqlite_saver(db_path))
        app1.invoke(HIGH_VALUE, thread_config(tid))
        assert app1.get_state(thread_config(tid)).next == ("human_gate",)

        app2 = build_graph(make_sqlite_saver(db_path))
        result = app2.invoke(
            Command(resume={"decision": "reject", "manager_note": "no"}), thread_config(tid)
        )
        assert result["status"] == ReturnStatus.rejected

    def test_checkpoint_file_created_and_nonempty(self, db_path):
        app = build_graph(make_sqlite_saver(db_path))
        app.invoke(DAMAGED_NO_PHOTO, thread_config(str(uuid.uuid4())))
        assert Path(db_path).exists()
        assert Path(db_path).stat().st_size > 0

    def test_unknown_thread_returns_empty_snapshot(self, db_path):
        app = build_graph(make_sqlite_saver(db_path))
        snap = app.get_state(thread_config("never-existed"))
        assert snap.values == {}
        assert snap.next == ()

    def test_state_snapshot_helper_reads_production_graph(self, db_path, monkeypatch):
        """get_state_snapshot / run_graph / resume_graph route to one graph."""
        import app.graph as g

        monkeypatch.setattr(g.settings, "SQLITE_DB_PATH", db_path)
        monkeypatch.setattr(g, "_default_graph", None)  # force rebuild

        tid = str(uuid.uuid4())
        result = g.run_graph(tid, dict(DAMAGED_NO_PHOTO))
        assert result["status"] == ReturnStatus.awaiting_photo

        snap = g.get_state_snapshot(tid)
        assert snap.next == ("check_photo_proof",)

        result2 = g.resume_graph(tid, {"photo_provided": True})
        assert result2["status"] == ReturnStatus.completed
        monkeypatch.setattr(g, "_default_graph", None)  # reset for other tests