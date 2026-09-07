"""Mock external services for the return agent (Phase 2).

Pure business logic with no LangGraph/FastAPI dependencies:

- In-memory mock order database (``MOCK_ORDERS``).
- In-memory customer return history (``MOCK_CUSTOMER_RETURN_HISTORY``).
- Return-window check (``is_within_return_window``).
- Shipping-fee rules (``calculate_shipping_fee``).
- Deterministic fraud heuristics (``compute_fraud_score``).
- Mock payment gateway (``process_refund``).

All weights/thresholds mirror the "Decisions" section of plan.md.
"""
from datetime import date, datetime, timedelta
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.schemas import ItemCondition


# ---------------------------------------------------------------------------
# Fraud heuristic constants (plan.md "Decisions")
# ---------------------------------------------------------------------------
VELOCITY_FLAG_WEIGHT: float = 0.4      # >= 3 returns in trailing 30 days
NO_PHOTO_FLAG_WEIGHT: float = 0.4      # damaged claim, no photo after retries exhausted
HIGH_REFUND_FLAG_WEIGHT: float = 0.3   # refund_amount > $500

VELOCITY_WINDOW_DAYS: int = 30
VELOCITY_RETURN_COUNT: int = 3
HIGH_REFUND_THRESHOLD: float = 500.00


# ---------------------------------------------------------------------------
# Mock data seeding helpers (dates relative to import time so the fixtures
# stay valid no matter when the suite runs)
# ---------------------------------------------------------------------------
def _days_ago_date(days: int) -> str:
    """ISO date string for *days* days before today."""
    return (date.today() - timedelta(days=days)).isoformat()


def _days_ago_ts(days: int) -> str:
    """ISO timestamp string for *days* days before now."""
    return (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------
#: order_id -> order record. Dates intentionally mixed: some fresh (< 30 days),
#: some stale (> 30 days); item values span cheap to high-ticket.
MOCK_ORDERS: Dict[str, Dict[str, Any]] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "customer_id": "CUST-A",
        "item_id": "SKU-LAPTOP-01",
        "item_name": 'Ultrabook 14"',
        "item_value": 899.00,
        "order_date": _days_ago_date(5),   # fresh, high value
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "customer_id": "CUST-B",
        "item_id": "SKU-HEADPHN-02",
        "item_name": "Wireless Headphones",
        "item_value": 129.50,
        "order_date": _days_ago_date(10),  # fresh, low value
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "customer_id": "CUST-C",
        "item_id": "SKU-KEYBOARD-03",
        "item_name": "Mechanical Keyboard",
        "item_value": 79.99,
        "order_date": _days_ago_date(45),  # outside return window
    },
    "ORD-1004": {
        "order_id": "ORD-1004",
        "customer_id": "CUST-A",
        "item_id": "SKU-MONITOR-04",
        "item_name": '27" 4K Monitor',
        "item_value": 349.00,
        "order_date": _days_ago_date(25),  # fresh, high value
    },
    "ORD-1005": {
        "order_id": "ORD-1005",
        "customer_id": "CUST-D",
        "item_id": "SKU-MOUSE-05",
        "item_name": "Ergonomic Mouse",
        "item_value": 45.00,
        "order_date": _days_ago_date(60),  # outside return window, low value
    },
    "ORD-1006": {
        "order_id": "ORD-1006",
        "customer_id": "CUST-D",
        "item_id": "SKU-CABLE-06",
        "item_name": "USB-C Cable",
        "item_value": 15.00,
        "order_date": _days_ago_date(2),   # very fresh, low value
    },
}

#: customer_id -> list of ISO timestamps of past returns.
#: CUST-A deliberately has 3 returns inside the trailing 30 days so the
#: velocity fraud flag (+0.4) can be exercised in tests.
MOCK_CUSTOMER_RETURN_HISTORY: Dict[str, List[str]] = {
    "CUST-A": [_days_ago_ts(5), _days_ago_ts(12), _days_ago_ts(20)],  # velocity trigger
    "CUST-B": [_days_ago_ts(15)],
    "CUST-C": [_days_ago_ts(40), _days_ago_ts(50)],  # all older than 30 days
    "CUST-D": [],
}


# ---------------------------------------------------------------------------
# Order lookups
# ---------------------------------------------------------------------------
def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    """Look up an order by id.

    Returns a shallow copy of the order record (so callers cannot mutate the
    mock DB), or ``None`` when the order id is unknown.
    """
    order = MOCK_ORDERS.get(order_id)
    return dict(order) if order is not None else None


# ---------------------------------------------------------------------------
# Policy rules
# ---------------------------------------------------------------------------
def _parse_order_date(value: Any) -> Optional[date]:
    """Best-effort parse of an order date (ISO string, date, or datetime)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None
    return None


def is_within_return_window(order_date: Any, window_days: int = 30) -> bool:
    """Return True when the order is within ``window_days`` of today.

    The window is inclusive (day 30 still qualifies) and future-dated orders
    are rejected. Unparseable/missing dates conservatively return ``False``.
    """
    parsed = _parse_order_date(order_date)
    if parsed is None:
        return False
    age_days = (date.today() - parsed).days
    return 0 <= age_days <= window_days


def calculate_shipping_fee(condition: ItemCondition) -> float:
    """Shipping fee per plan.md Decisions.

    ``damaged_defective`` -> $0.00 (merchant's fault).
    ``buyer_remorse``    -> $5.99 flat fee.
    ``unknown``          -> $5.99 (charged as buyer's remorse until the
    condition is proven damaged; the classifier never emits ``unknown`` on
    the happy path, so this is a defensive default).
    """
    if condition == ItemCondition.damaged_defective:
        return settings.DAMAGED_FEE
    return settings.BUYERS_REMORSE_FEE


# ---------------------------------------------------------------------------
# Fraud heuristics
# ---------------------------------------------------------------------------
def _count_returns_in_window(customer_id: str, window_days: int) -> int:
    """Number of past returns for ``customer_id`` within the last *window_days*."""
    history = MOCK_CUSTOMER_RETURN_HISTORY.get(customer_id, [])
    now = datetime.now()
    cutoff = now - timedelta(days=window_days)
    count = 0
    for raw in history:
        try:
            ts = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if cutoff <= ts <= now:
            count += 1
    return count


def compute_fraud_score(
    customer_id: str,
    refund_amount: float,
    photo_provided: bool,
    photo_retries_exhausted: bool = False,
) -> Tuple[float, List[str]]:
    """Deterministic fraud score + human-readable flags (plan.md Decisions).

    Weights (exact sums, no cap — thresholding happens in the graph):

    - ``+0.4`` ``high_return_velocity``: customer has >= 3 returns in the
      trailing 30 days (mock history lookup).
    - ``+0.4`` ``no_photo_proof``: the photo loop exhausted
      ``MAX_PHOTO_RETRIES`` without a photo. The caller (graph node) passes
      ``photo_retries_exhausted=True`` only for damaged/defective claims, so
      a plain "no photo on a buyer's-remorse return" does *not* trip this.
    - ``+0.3`` ``high_refund_amount``: ``refund_amount`` > $500.

    Returns ``(score, flags)``; the score is rounded to 2 decimals.
    """
    score = 0.0
    flags: List[str] = []

    if _count_returns_in_window(customer_id, VELOCITY_WINDOW_DAYS) >= VELOCITY_RETURN_COUNT:
        score += VELOCITY_FLAG_WEIGHT
        flags.append("high_return_velocity")

    if photo_retries_exhausted and not photo_provided:
        score += NO_PHOTO_FLAG_WEIGHT
        flags.append("no_photo_proof")

    if refund_amount > HIGH_REFUND_THRESHOLD:
        score += HIGH_REFUND_FLAG_WEIGHT
        flags.append("high_refund_amount")

    return round(score, 2), flags


# ---------------------------------------------------------------------------
# Mock payment gateway
# ---------------------------------------------------------------------------
def process_refund(order_id: str, amount: float) -> Dict[str, Any]:
    """Mock payment gateway call — always succeeds.

    Returns a gateway-style receipt dict with a fake transaction id.
    """
    return {
        "status": "success",
        "transaction_id": f"TXN-{uuid.uuid4().hex[:12].upper()}",
        "order_id": order_id,
        "amount": round(amount, 2),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    }