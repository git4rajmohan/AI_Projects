"""Integration tests for the FastAPI layer (Phase 6).

Covers the five routes from plan.md:

- ``POST /returns`` — start a workflow (remorse auto-complete, photo loop,
  manager gate, policy denial, invalid body)
- ``POST /returns/{thread_id}/photo`` — resume the photo-proof interrupt
- ``POST /returns/{thread_id}/approve`` / ``/reject`` — resume the manager gate
- ``GET  /returns/{thread_id}`` — inspect checkpointed state

Error semantics: 404 unknown thread, 409 wrong/absent pause, 422 invalid body.
Also verifies checkpointed state survives a full graph-instance rebuild on
the same sqlite file (the API-level equivalent of a server restart).
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app import graph as graph_module
from app.graph import classify_condition_stub
from app.main import app as fastapi_app


@pytest.fixture(autouse=True)
def stub_llm_classifier(monkeypatch):
    """Keep API tests deterministic: keyword stub instead of the live LLM."""
    monkeypatch.setattr(graph_module.llm, "classify_reason", classify_condition_stub)
    monkeypatch.setattr(
        graph_module.llm,
        "classify_reason_with_source",
        lambda reason: (classify_condition_stub(reason), "llm"),
    )


def _reset_default_graph() -> None:
    """Drop the cached production graph and close its sqlite connection."""
    cached = graph_module._default_graph
    if cached is not None:
        conn = getattr(cached.checkpointer, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    graph_module._default_graph = None


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    """TestClient on a throwaway sqlite checkpoint file (fresh per test)."""
    db_path = tmp_path / "api_checkpoints.sqlite"
    monkeypatch.setattr(config.settings, "SQLITE_DB_PATH", str(db_path))
    _reset_default_graph()
    yield TestClient(fastapi_app)
    _reset_default_graph()


# ---------------------------------------------------------------------------
# Request payloads (mirror the mock orders in services.py)
# ---------------------------------------------------------------------------
BUYERS_REMORSE = {
    "order_id": "ORD-1002",   # fresh, $129.50, CUST-B (clean history)
    "item_id": "SKU-HEADPHN-02",
    "reason_text": "Changed my mind, ordered the wrong model",
    "photo_provided": False,
}
DAMAGED_NO_PHOTO = {
    "order_id": "ORD-1002",
    "item_id": "SKU-HEADPHN-02",
    "reason_text": "Headphones arrived broken",
    "photo_provided": False,
}
HIGH_VALUE = {
    "order_id": "ORD-1001",   # fresh, $899.00, CUST-A (velocity flag)
    "item_id": "SKU-LAPTOP-01",
    "reason_text": "Just don't want it",
    "photo_provided": False,
}
OLD_ORDER = {
    "order_id": "ORD-1003",   # 45 days old
    "item_id": "SKU-KEYBOARD-03",
    "reason_text": "Stopped working",
    "photo_provided": True,
}


class TestCreateReturn:
    def test_buyers_remorse_auto_completes(self, client):
        """Low-value remorse return runs to completion with the $5.99 fee."""
        resp = client.post("/returns", json=BUYERS_REMORSE)
        assert resp.status_code == 200
        body = resp.json()
        uuid.UUID(body["thread_id"])  # valid uuid4 thread id
        assert body["status"] == "completed"
        assert body["next_action"] == "none"
        assert body["order_id"] == "ORD-1002"
        assert body["item_id"] == "SKU-HEADPHN-02"
        assert body["reason_text"] == "Changed my mind, ordered the wrong model"
        assert body["shipping_fee"] == pytest.approx(5.99)
        assert body["refund_amount"] == pytest.approx(123.51)  # 129.50 - 5.99
        assert body["fraud_score"] == pytest.approx(0.0)
        assert body["fraud_flags"] == []
        assert body["manager_note"] is None
        # Audit trail: validate + classify + fee + fraud + finalize all logged.
        log = body["decision_log"]
        assert len(log) == 5
        assert "order 'ORD-1002' validated" in log[0]
        assert "classified as 'buyer_remorse'" in log[1]
        assert "shipping fee $5.99" in log[2]
        assert "fraud score 0.00" in log[3]
        assert "refund $123.51" in log[4] and "txn" in log[4]

    def test_invalid_body_returns_422(self, client):
        resp = client.post("/returns", json={"reason_text": "missing ids"})
        assert resp.status_code == 422


class TestPhotoLoop:
    def test_damaged_no_photo_pauses_then_completes(self, client):
        """Damaged claim without photo → awaiting_photo → photo → completed."""
        resp = client.post("/returns", json=DAMAGED_NO_PHOTO)
        assert resp.status_code == 200
        body = resp.json()
        tid = body["thread_id"]
        assert body["status"] == "awaiting_photo"
        assert body["next_action"] == "submit_photo"
        assert body["refund_amount"] is None  # fee/fraud stages not reached yet

        # GET reflects the paused checkpoint state
        got = client.get(f"/returns/{tid}")
        assert got.status_code == 200
        assert got.json()["status"] == "awaiting_photo"
        assert got.json()["next_action"] == "submit_photo"

        # Photo resubmission resumes the loop and completes with $0 fee
        done = client.post(
            f"/returns/{tid}/photo",
            json={"photo_provided": True, "photo_url": "http://x/p.jpg"},
        )
        assert done.status_code == 200
        final = done.json()
        assert final["status"] == "completed"
        assert final["shipping_fee"] == pytest.approx(0.0)
        assert final["refund_amount"] == pytest.approx(129.50)
        assert final["fraud_flags"] == []
        assert final["next_action"] == "none"

    def test_empty_photo_resubmission_keeps_looping(self, client):
        """Resuming with photo_provided=false re-pauses instead of completing."""
        tid = client.post("/returns", json=DAMAGED_NO_PHOTO).json()["thread_id"]
        again = client.post(f"/returns/{tid}/photo", json={"photo_provided": False})
        assert again.status_code == 200
        assert again.json()["status"] == "awaiting_photo"
        assert again.json()["next_action"] == "submit_photo"

        done = client.post(f"/returns/{tid}/photo", json={"photo_provided": True})
        assert done.json()["status"] == "completed"

    def test_photo_on_manager_gate_conflicts(self, client):
        tid = client.post("/returns", json=HIGH_VALUE).json()["thread_id"]
        resp = client.post(f"/returns/{tid}/photo", json={"photo_provided": True})
        assert resp.status_code == 409
        assert "human_gate" in resp.json()["detail"]

    def test_photo_on_completed_thread_conflicts(self, client):
        tid = client.post("/returns", json=BUYERS_REMORSE).json()["thread_id"]
        resp = client.post(f"/returns/{tid}/photo", json={"photo_provided": True})
        assert resp.status_code == 409

    def test_photo_unknown_thread_404(self, client):
        resp = client.post(
            f"/returns/{uuid.uuid4()}/photo", json={"photo_provided": True}
        )
        assert resp.status_code == 404


class TestManagerGate:
    def test_high_value_awaits_then_approve_completes(self, client):
        """Refund > $200 pauses at the gate; approve → completed."""
        body = client.post("/returns", json=HIGH_VALUE).json()
        tid = body["thread_id"]
        assert body["status"] == "awaiting_approval"
        assert body["next_action"] == "await_manager"
        assert body["refund_amount"] == pytest.approx(893.01)  # 899 - 5.99
        # CUST-A velocity (0.4) + refund > $500 (0.3) = 0.7
        assert body["fraud_score"] == pytest.approx(0.7)
        assert sorted(body["fraud_flags"]) == [
            "high_refund_amount",
            "high_return_velocity",
        ]

        got = client.get(f"/returns/{tid}")
        assert got.json()["status"] == "awaiting_approval"

        done = client.post(f"/returns/{tid}/approve", json={"manager_note": "verified"})
        assert done.status_code == 200
        final = done.json()
        assert final["status"] == "completed"
        assert final["manager_note"] == "verified"
        assert final["refund_amount"] == pytest.approx(893.01)
        assert final["next_action"] == "none"

    def test_high_value_reject(self, client):
        tid = client.post("/returns", json=HIGH_VALUE).json()["thread_id"]
        done = client.post(f"/returns/{tid}/reject", json={"manager_note": "suspicious"})
        assert done.status_code == 200
        final = done.json()
        assert final["status"] == "rejected"
        assert final["manager_note"] == "suspicious"
        assert final["refund_amount"] == pytest.approx(893.01)  # computed, not paid
        assert final["next_action"] == "none"

    def test_approve_on_completed_thread_conflicts(self, client):
        tid = client.post("/returns", json=BUYERS_REMORSE).json()["thread_id"]
        resp = client.post(f"/returns/{tid}/approve", json={})
        assert resp.status_code == 409

    def test_approve_on_photo_paused_thread_conflicts(self, client):
        tid = client.post("/returns", json=DAMAGED_NO_PHOTO).json()["thread_id"]
        resp = client.post(f"/returns/{tid}/approve", json={})
        assert resp.status_code == 409
        assert "check_photo_proof" in resp.json()["detail"]

    def test_approve_unknown_thread_404(self, client):
        resp = client.post(f"/returns/{uuid.uuid4()}/approve", json={})
        assert resp.status_code == 404


class TestPolicyDenial:
    def test_old_order_denied_immediately(self, client):
        body = client.post("/returns", json=OLD_ORDER).json()
        assert body["status"] == "denied_policy"
        assert body["next_action"] == "none"
        assert body["refund_amount"] is None  # fee/fraud stages never ran

    def test_get_denied_thread(self, client):
        tid = client.post("/returns", json=OLD_ORDER).json()["thread_id"]
        got = client.get(f"/returns/{tid}")
        assert got.status_code == 200
        assert got.json()["status"] == "denied_policy"


class TestGetErrors:
    def test_get_unknown_thread_404(self, client):
        resp = client.get(f"/returns/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestPersistenceAcrossRebuild:
    def test_paused_state_survives_graph_rebuild(self, client):
        """Fresh SqliteSaver on the same sqlite file ≡ server restart."""
        tid = client.post("/returns", json=HIGH_VALUE).json()["thread_id"]
        assert client.get(f"/returns/{tid}").json()["status"] == "awaiting_approval"

        _reset_default_graph()  # simulate restart: drop cached graph/connection

        got = client.get(f"/returns/{tid}")
        assert got.status_code == 200
        assert got.json()["status"] == "awaiting_approval"

        done = client.post(f"/returns/{tid}/approve", json={"manager_note": "ok"})
        assert done.json()["status"] == "completed"


class TestListOrders:
    def test_lists_six_seeded_mock_orders(self, client):
        """GET /orders returns every seeded mock order with full summaries."""
        resp = client.get("/orders")
        assert resp.status_code == 200
        orders = resp.json()
        assert len(orders) == 6
        by_id = {o["order_id"]: o for o in orders}
        assert set(by_id) == {
            "ORD-1001", "ORD-1002", "ORD-1003",
            "ORD-1004", "ORD-1005", "ORD-1006",
        }
        laptop = by_id["ORD-1001"]
        assert laptop["item_id"] == "SKU-LAPTOP-01"
        assert laptop["item_name"] == 'Ultrabook 14"'
        assert laptop["item_value"] == pytest.approx(899.00)
        assert laptop["order_date"]  # ISO date string present


class TestListReturns:
    def test_empty_before_any_run(self, client):
        """GET /returns with no checkpointed threads returns []."""
        assert client.get("/returns").json() == []

    def test_includes_created_threads_with_identifiers(self, client):
        """Every started return appears in the list with identifier fields."""
        first = client.post("/returns", json=BUYERS_REMORSE).json()
        second = client.post("/returns", json=HIGH_VALUE).json()

        listed = client.get("/returns").json()
        ids = {r["thread_id"] for r in listed}
        assert ids == {first["thread_id"], second["thread_id"]}
        by_tid = {r["thread_id"]: r for r in listed}
        assert by_tid[first["thread_id"]]["order_id"] == "ORD-1002"
        assert by_tid[first["thread_id"]]["item_id"] == "SKU-HEADPHN-02"
        assert by_tid[first["thread_id"]]["reason_text"] == (
            "Changed my mind, ordered the wrong model"
        )
        assert by_tid[second["thread_id"]]["order_id"] == "ORD-1001"

    def test_filters_by_status(self, client):
        """?status=awaiting_approval returns only paused-at-gate threads."""
        remorse_tid = client.post("/returns", json=BUYERS_REMORSE).json()["thread_id"]
        high_tid = client.post("/returns", json=HIGH_VALUE).json()["thread_id"]

        pending = client.get("/returns", params={"status": "awaiting_approval"}).json()
        assert [r["thread_id"] for r in pending] == [high_tid]

        all_returns = client.get("/returns").json()
        assert {r["thread_id"] for r in all_returns} == {remorse_tid, high_tid}

    def test_filter_by_completed_after_photo_loop(self, client):
        """A photo-loop thread shows as awaiting_photo, then completed."""
        tid = client.post("/returns", json=DAMAGED_NO_PHOTO).json()["thread_id"]
        awaiting = client.get("/returns", params={"status": "awaiting_photo"}).json()
        assert [r["thread_id"] for r in awaiting] == [tid]

        client.post(f"/returns/{tid}/photo", json={"photo_provided": True})
        completed = client.get("/returns", params={"status": "completed"}).json()
        assert [r["thread_id"] for r in completed] == [tid]

    def test_invalid_status_422(self, client):
        resp = client.get("/returns", params={"status": "not-a-status"})
        assert resp.status_code == 422