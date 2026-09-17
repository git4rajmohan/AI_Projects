"""Unit tests for app.services — Phase 2 verification (table-driven)."""
from datetime import date, datetime, timedelta

import pytest

from app.schemas import ItemCondition
from app.services import (
    HIGH_REFUND_FLAG_WEIGHT,
    HIGH_REFUND_THRESHOLD,
    NO_PHOTO_FLAG_WEIGHT,
    VELOCITY_FLAG_WEIGHT,
    MOCK_ORDERS,
    calculate_shipping_fee,
    compute_fraud_score,
    get_order,
    is_within_return_window,
    process_refund,
)


# ---------------------------------------------------------------------------
# get_order — mock order DB
# ---------------------------------------------------------------------------
class TestGetOrder:
    @pytest.mark.parametrize(
        ("order_id", "expected_customer", "expected_value"),
        [
            ("ORD-1001", "CUST-A", 899.00),
            ("ORD-1002", "CUST-B", 129.50),
            ("ORD-1003", "CUST-C", 79.99),
            ("ORD-1004", "CUST-A", 349.00),
            ("ORD-1005", "CUST-D", 45.00),
        ],
    )
    def test_known_orders(self, order_id, expected_customer, expected_value):
        order = get_order(order_id)
        assert order is not None
        assert order["customer_id"] == expected_customer
        assert order["item_value"] == expected_value
        assert "order_date" in order

    def test_unknown_order_returns_none(self):
        assert get_order("ORD-DOES-NOT-EXIST") is None
        assert get_order("") is None

    def test_at_least_five_orders_seeded(self):
        # plan.md requires >= 5 sample orders
        assert len(MOCK_ORDERS) >= 5

    def test_copy_semantics(self):
        """Mutation must not leak into the mock DB."""
        order = get_order("ORD-1001")
        order["item_value"] = 0.01
        assert get_order("ORD-1001")["item_value"] == 899.00


# ---------------------------------------------------------------------------
# is_within_return_window — table-driven in/out of range
# ---------------------------------------------------------------------------
class TestIsWithinReturnWindow:
    @pytest.mark.parametrize(
        ("age_days", "expected"),
        [
            (0, True),    # today
            (1, True),    # yesterday
            (15, True),   # mid-window
            (29, True),   # just inside
            (30, True),   # boundary — inclusive per implementation
            (31, False),  # one day past
            (45, False),  # well outside
            (365, False), # a year old
        ],
    )
    def test_age_days_table(self, age_days, expected):
        order_date = (date.today() - timedelta(days=age_days)).isoformat()
        assert is_within_return_window(order_date) is expected

    def test_future_order_rejected(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        assert is_within_return_window(future) is False

    @pytest.mark.parametrize("bad", [None, "", "not-a-date", "2026/13/45"])
    def test_unparseable_dates_rejected(self, bad):
        assert is_within_return_window(bad) is False

    def test_datetime_input_accepted(self):
        recent = datetime.now() - timedelta(days=3)
        assert is_within_return_window(recent) is True

    def test_custom_window(self):
        order_date = (date.today() - timedelta(days=60)).isoformat()
        assert is_within_return_window(order_date, window_days=90) is True
        assert is_within_return_window(order_date, window_days=14) is False

    def test_mock_orders_match_expectations(self):
        # Fresh orders in the mock DB must pass; stale ones must fail.
        assert is_within_return_window(get_order("ORD-1001")["order_date"]) is True
        assert is_within_return_window(get_order("ORD-1002")["order_date"]) is True
        assert is_within_return_window(get_order("ORD-1003")["order_date"]) is False
        assert is_within_return_window(get_order("ORD-1004")["order_date"]) is True
        assert is_within_return_window(get_order("ORD-1005")["order_date"]) is False
        assert is_within_return_window(get_order("ORD-1006")["order_date"]) is True


# ---------------------------------------------------------------------------
# calculate_shipping_fee — both conditions per Decisions
# ---------------------------------------------------------------------------
class TestCalculateShippingFee:
    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            (ItemCondition.damaged_defective, 0.00),
            (ItemCondition.buyer_remorse, 5.99),
            (ItemCondition.unknown, 5.99),  # defensive default
        ],
    )
    def test_fee_table(self, condition, expected):
        assert calculate_shipping_fee(condition) == pytest.approx(expected)

    def test_works_with_raw_string_values(self):
        assert calculate_shipping_fee(ItemCondition("damaged_defective")) == pytest.approx(0.0)
        assert calculate_shipping_fee(ItemCondition("buyer_remorse")) == pytest.approx(5.99)


# ---------------------------------------------------------------------------
# compute_fraud_score — exact sums per Decisions weights
# ---------------------------------------------------------------------------
class TestComputeFraudScore:
    def test_no_flags(self):
        """Low-velocity customer, photo provided, modest refund -> 0.0."""
        score, flags = compute_fraud_score("CUST-D", 45.00, photo_provided=True)
        assert score == pytest.approx(0.0)
        assert flags == []

    def test_velocity_flag_only(self):
        """CUST-A has 3 returns in trailing 30 days -> exactly +0.4."""
        score, flags = compute_fraud_score("CUST-A", 129.50, photo_provided=True)
        assert score == pytest.approx(VELOCITY_FLAG_WEIGHT)  # 0.4
        assert flags == ["high_return_velocity"]

    def test_high_refund_flag_only(self):
        """Refund > $500 -> exactly +0.3."""
        score, flags = compute_fraud_score("CUST-B", 899.00, photo_provided=True)
        assert score == pytest.approx(HIGH_REFUND_FLAG_WEIGHT)  # 0.3
        assert flags == ["high_refund_amount"]

    def test_no_photo_flag_requires_retries_exhausted(self):
        """Damaged claim + no photo *only* scores once retries are exhausted."""
        base = compute_fraud_score("CUST-B", 129.50, photo_provided=False,
                                   photo_retries_exhausted=False)
        assert base == (0.0, [])

        flagged = compute_fraud_score("CUST-B", 129.50, photo_provided=False,
                                      photo_retries_exhausted=True)
        assert flagged[0] == pytest.approx(NO_PHOTO_FLAG_WEIGHT)  # 0.4
        assert flagged[1] == ["no_photo_proof"]

    def test_all_three_flags_stack(self):
        """Velocity (0.4) + no-photo (0.4) + high refund (0.3) = 1.1 exactly."""
        score, flags = compute_fraud_score(
            "CUST-A", 899.00, photo_provided=False, photo_retries_exhausted=True,
        )
        expected = VELOCITY_FLAG_WEIGHT + NO_PHOTO_FLAG_WEIGHT + HIGH_REFUND_FLAG_WEIGHT
        assert score == pytest.approx(expected)  # 1.1
        assert set(flags) == {"high_return_velocity", "no_photo_proof", "high_refund_amount"}
        assert len(flags) == 3

    def test_velocity_and_high_refund_stack(self):
        """Two flags: 0.4 + 0.3 = 0.7 — exactly at FRAUD_SCORE_THRESHOLD."""
        score, flags = compute_fraud_score("CUST-A", 899.00, photo_provided=True)
        assert score == pytest.approx(0.7)
        assert sorted(flags) == ["high_refund_amount", "high_return_velocity"]

    def test_boundary_refund_not_flagged(self):
        """Refund exactly $500 must NOT trip the high-refund flag (> strict)."""
        score, flags = compute_fraud_score("CUST-D", HIGH_REFUND_THRESHOLD, photo_provided=True)
        assert score == pytest.approx(0.0)
        assert flags == []

    def test_unknown_customer_history_is_empty(self):
        score, flags = compute_fraud_score("CUST-NOBODY", 45.00, photo_provided=True)
        assert score == pytest.approx(0.0)
        assert flags == []

    def test_cust_c_history_is_stale(self):
        """CUST-C returns are all > 30 days old -> no velocity flag."""
        score, flags = compute_fraud_score("CUST-C", 79.99, photo_provided=True)
        assert score == pytest.approx(0.0)
        assert flags == []

    def test_score_is_rounded(self):
        score, _ = compute_fraud_score("CUST-A", 500.01, photo_provided=True)
        assert score == round(score, 2)


# ---------------------------------------------------------------------------
# process_refund — mock payment gateway
# ---------------------------------------------------------------------------
class TestProcessRefund:
    def test_returns_success_shape(self):
        receipt = process_refund("ORD-1002", 129.50)
        assert receipt["status"] == "success"
        assert receipt["order_id"] == "ORD-1002"
        assert receipt["amount"] == pytest.approx(129.50)
        assert isinstance(receipt["transaction_id"], str)
        assert receipt["transaction_id"].startswith("TXN-")

    def test_transaction_ids_unique(self):
        ids = {process_refund("ORD-1001", 10.00)["transaction_id"] for _ in range(10)}
        assert len(ids) == 10

    def test_amount_rounded_to_two_decimals(self):
        receipt = process_refund("ORD-1001", 123.456789)
        assert receipt["amount"] == pytest.approx(123.46)

    def test_zero_amount_succeeds(self):
        receipt = process_refund("ORD-1006", 0.0)
        assert receipt["status"] == "success"
        assert receipt["amount"] == pytest.approx(0.0)