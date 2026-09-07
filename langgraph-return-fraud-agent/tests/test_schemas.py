"""Unit tests for app.schemas — Phase 1 verification."""
import pytest
from pydantic import ValidationError

from app.schemas import (
    ApprovalRequest,
    ItemCondition,
    PhotoResubmitRequest,
    ReturnRequest,
    ReturnResponse,
    ReturnState,
    ReturnStatus,
)


# ---------------------------------------------------------------------------
# ItemCondition enum
# ---------------------------------------------------------------------------
class TestItemCondition:
    def test_valid_values(self):
        assert ItemCondition("damaged_defective") == ItemCondition.damaged_defective
        assert ItemCondition("buyer_remorse") == ItemCondition.buyer_remorse
        assert ItemCondition("unknown") == ItemCondition.unknown

    @pytest.mark.parametrize("bad", ["broken", "defective", "", "DAMAGED_DEFECTIVE"])
    def test_invalid_value_raises(self, bad):
        with pytest.raises(ValueError):
            ItemCondition(bad)


# ---------------------------------------------------------------------------
# ReturnStatus enum
# ---------------------------------------------------------------------------
class TestReturnStatus:
    def test_all_statuses_exist(self):
        expected = {
            "pending", "awaiting_photo", "awaiting_approval", "approved",
            "rejected", "completed", "denied_policy",
        }
        assert {s.value for s in ReturnStatus} == expected

    @pytest.mark.parametrize("bad", ["done", "waiting", ""])
    def test_invalid_value_raises(self, bad):
        with pytest.raises(ValueError):
            ReturnStatus(bad)


# ---------------------------------------------------------------------------
# ReturnState (LangGraph state)
# ---------------------------------------------------------------------------
class TestReturnState:
    def test_valid_minimal_construction(self):
        state = ReturnState(order_id="ORD-1", item_id="SKU-1", reason_text="broken")
        assert state.status == ReturnStatus.pending
        assert state.item_condition == ItemCondition.unknown
        assert state.photo_retry_count == 0
        assert state.fraud_flags == []
        assert state.decision_log == []
        assert state.refund_amount == 0.0

    def test_full_construction(self):
        state = ReturnState(
            order_id="ORD-2",
            customer_id="CUST-1",
            item_id="SKU-2",
            reason_text="arrived cracked",
            photo_provided=True,
            photo_url="https://example.com/p.jpg",
            item_condition=ItemCondition.damaged_defective,
            item_value=250.0,
            shipping_fee=0.0,
            refund_amount=250.0,
            fraud_score=0.4,
            fraud_flags=["high_value"],
            status=ReturnStatus.awaiting_approval,
            manager_note=None,
            decision_log=["classified"],
        )
        assert state.fraud_flags == ["high_value"]
        assert state.status == ReturnStatus.awaiting_approval

    def test_missing_required_fields_raise(self):
        with pytest.raises(ValidationError):
            ReturnState(order_id="ORD-3")  # missing item_id, reason_text
        with pytest.raises(ValidationError):
            ReturnState(item_id="SKU-3", reason_text="x")  # missing order_id
        with pytest.raises(ValidationError):
            ReturnState(order_id="ORD-4", item_id="SKU-4")  # missing reason_text

    def test_invalid_enum_raises(self):
        with pytest.raises(ValidationError):
            ReturnState(order_id="o", item_id="i", reason_text="r", item_condition="smashed")
        with pytest.raises(ValidationError):
            ReturnState(order_id="o", item_id="i", reason_text="r", status="zombie")

    def test_invalid_types_raise(self):
        with pytest.raises(ValidationError):
            ReturnState(order_id="o", item_id="i", reason_text="r", item_value="free")
        with pytest.raises(ValidationError):
            ReturnState(order_id="o", item_id="i", reason_text="r", photo_retry_count="three")


# ---------------------------------------------------------------------------
# API contracts
# ---------------------------------------------------------------------------
class TestReturnRequest:
    def test_valid(self):
        req = ReturnRequest(order_id="ORD-1", item_id="SKU-1", reason_text="damaged")
        assert req.photo_provided is False
        assert req.photo_url is None

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            ReturnRequest(order_id="ORD-1", reason_text="why")  # missing item_id
        with pytest.raises(ValidationError):
            ReturnRequest(item_id="SKU-1")  # missing order_id & reason_text


class TestReturnResponse:
    def test_valid_minimal(self):
        resp = ReturnResponse(thread_id="t-1", status=ReturnStatus.completed, message="ok")
        assert resp.next_action is None
        assert resp.fraud_flags == []

    def test_next_action_limited_values(self):
        ReturnResponse(thread_id="t", status=ReturnStatus.completed, message="m", next_action="none")
        with pytest.raises(ValidationError):
            ReturnResponse(thread_id="t", status=ReturnStatus.completed, message="m", next_action="dance")

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            ReturnResponse(thread_id="t-1", status=ReturnStatus.completed)  # missing message


class TestApprovalRequest:
    def test_valid_empty(self):
        assert ApprovalRequest().manager_note is None

    def test_valid_with_note(self):
        req = ApprovalRequest(manager_note="checked with customer")
        assert req.manager_note == "checked with customer"

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            ApprovalRequest(manager_note=123)


class TestPhotoResubmitRequest:
    def test_defaults(self):
        req = PhotoResubmitRequest()
        assert req.photo_provided is True
        assert req.photo_url is None

    def test_valid_full(self):
        req = PhotoResubmitRequest(photo_provided=True, photo_url="https://x.com/p.jpg")
        assert req.photo_url == "https://x.com/p.jpg"

    def test_invalid_type_raises(self):
        # pydantic v2 lax mode coerces "yes"/"true"/"1" to bool; "maybe" is not coercible
        with pytest.raises(ValidationError):
            PhotoResubmitRequest(photo_provided="maybe")