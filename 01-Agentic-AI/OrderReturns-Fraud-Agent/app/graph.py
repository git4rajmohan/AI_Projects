"""LangGraph state machine for the return agent (Phase 4: interrupts + SQLite).

Graph topology::

    START
      └─> validate_policy ──(denied)──> reject_policy ──> END
              │ (ok)
              └─> classify_condition
                      └─> check_photo_proof ─┐(photo outstanding & retries left)
                            │    ^           └── loops back to itself
                            │    └── interrupt() pauses here until the client
                            │        resubmits a photo (bounded by MAX_PHOTO_RETRIES)
                            │ (proof received / retries exhausted)
                            └─> calculate_fee
                                    └─> fraud_check ──(refund > $200 / fraud score /
                                            │                   no_photo_proof flag)
                                            │                     └─> human_gate ─┐(first pass
                                            │ (clean)                              │ sets status,
                                            └───────────────> finalize_refund <──┐ │ then loops
                                                                              │ │ back and
                                                                              │ │ interrupt()s)
                                            (approve) ────────────────────────┘ │
                                            (reject) ──> reject_by_manager ──> END

Phase 4 notes:
- ``check_photo_proof_node`` pauses via ``interrupt({"reason": "photo_required", ...})``
  for damaged/defective claims without a photo. Resume value
  ``{"photo_provided": bool, "photo_url": str|None}`` updates the photo fields and
  increments ``photo_retry_count``; the conditional edge loops back into the same
  node until proof arrives or ``MAX_PHOTO_RETRIES`` is exhausted (then it proceeds
  and the fraud node flags ``no_photo_proof``).
- ``human_gate_node`` pauses via ``interrupt({"reason": "manager_approval_required", ...})``;
  resume value ``{"decision": "approve"|"reject", "manager_note": str|None}`` routes to
  ``finalize_refund_node`` or ``reject_by_manager_node``.
- Both gates set their pause status (``awaiting_photo`` / ``awaiting_approval``) on a
  first pass and loop back to themselves for the ``interrupt()`` pass, so the
  checkpointed state exposes the pause status to the API layer while paused.
- ``classify_condition_node`` delegates to the Ollama-cloud LLM classifier
  (``app/llm.py``) with the deterministic keyword stub as fallback; the audit
  log records which classifier produced the label.
- ``graph`` (module singleton) compiles with **no checkpointer** for unit tests and
  structural inspection. The production graph used by the API layer comes from
  :func:`get_default_graph` (SqliteSaver at ``settings.SQLITE_DB_PATH``) via
  :func:`run_graph` / :func:`resume_graph` / :func:`get_state_snapshot`.
"""
import sqlite3
from typing import Any, Dict, List, Optional

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import (
    BaseCheckpointSaver,
    Command,
    StateSnapshot,
    interrupt,
)

from app import llm, services
from app.config import settings
from app.schemas import ItemCondition, ReturnState, ReturnStatus


# ---------------------------------------------------------------------------
# Node names (single source of truth for wiring and tests)
# ---------------------------------------------------------------------------
VALIDATE_POLICY = "validate_policy"
CLASSIFY_CONDITION = "classify_condition"
CHECK_PHOTO_PROOF = "check_photo_proof"
CALCULATE_FEE = "calculate_fee"
FRAUD_CHECK = "fraud_check"
HUMAN_GATE = "human_gate"
FINALIZE_REFUND = "finalize_refund"
REJECT_POLICY = "reject_policy"
REJECT_BY_MANAGER = "reject_by_manager"


# ---------------------------------------------------------------------------
# Stub classifier (Phase 3) — kept as explicit fallback for Phase 5's LLM
# ---------------------------------------------------------------------------
_DAMAGED_KEYWORDS: tuple = (
    "broken",
    "defect",
    "damaged",
    "cracked",
    "malfunction",
    "not working",
    "stopped working",
    "dead on arrival",
    "doa",
)


def classify_condition_stub(reason_text: str) -> ItemCondition:
    """Keyword fallback classifier.

    ``damaged_defective`` when the reason text mentions damage/defect
    keywords, otherwise ``buyer_remorse``.
    """
    text = (reason_text or "").lower()
    if any(keyword in text for keyword in _DAMAGED_KEYWORDS):
        return ItemCondition.damaged_defective
    return ItemCondition.buyer_remorse


# ---------------------------------------------------------------------------
# Nodes — plain functions on ReturnState returning partial-dict updates
# ---------------------------------------------------------------------------
def validate_policy_node(state: ReturnState) -> Dict[str, Any]:
    """Look up the order and enforce the 30-day return window.

    Short-circuits to ``denied_policy`` when the order is unknown or outside
    the window; otherwise records the order facts onto the state.
    """
    order = services.get_order(state.order_id)
    if order is None:
        return {
            "status": ReturnStatus.denied_policy,
            "decision_log": list(state.decision_log)
            + [f"order '{state.order_id}' not found in order database"],
        }

    log: List[str] = [
        f"order '{order['order_id']}' validated "
        f"(value ${order['item_value']:.2f}, placed {order['order_date']})"
    ]
    updates: Dict[str, Any] = {
        "customer_id": order["customer_id"],
        "order_date": order["order_date"],
        "item_value": order["item_value"],
        "decision_log": list(state.decision_log) + log,
    }

    window_days = settings.RETURN_WINDOW_DAYS
    if not services.is_within_return_window(order["order_date"], window_days=window_days):
        updates["status"] = ReturnStatus.denied_policy
        updates["decision_log"] = updates["decision_log"] + [
            f"order placed {order['order_date']} is outside the {window_days}-day return window"
        ]
    return updates


def classify_condition_node(state: ReturnState) -> Dict[str, Any]:
    """Classify the free-text return reason into an item condition (LLM).

    Delegates to ``app.llm.classify_reason_with_source`` which calls Ollama
    Cloud and falls back to the keyword stub on any LLM failure. The audit
    log records *which* classifier produced the label so the UI can show it.
    """
    condition, classifier = llm.classify_reason_with_source(state.reason_text)
    if classifier == "llm":
        detail = f"LLM classifier: {settings.OLLAMA_MODEL}"
    else:
        detail = "keyword fallback classifier (LLM unavailable or unparseable)"
    return {
        "item_condition": condition,
        "decision_log": list(state.decision_log)
        + [f"return reason classified as '{condition.value}' ({detail})"],
    }


def check_photo_proof_node(state: ReturnState) -> Dict[str, Any]:
    """Require photo proof for damaged/defective claims (cyclical interrupt loop).

    Pass 1 (first arrival): mark ``awaiting_photo`` and loop back to this node.
    Pass 2: ``interrupt()`` until the client resumes with
    ``{"photo_provided": bool, "photo_url": str|None}``; the resume updates the
    photo fields and increments ``photo_retry_count``. When retries are
    exhausted the graph proceeds without proof (fraud node flags it).
    """
    needs_photo = (
        state.item_condition == ItemCondition.damaged_defective
        and not state.photo_provided
    )
    if not needs_photo:
        return {}

    if state.photo_retry_count >= settings.MAX_PHOTO_RETRIES:
        return {
            "decision_log": list(state.decision_log)
            + [
                f"photo retries exhausted ({state.photo_retry_count}/"
                f"{settings.MAX_PHOTO_RETRIES}) — proceeding without proof"
            ],
        }

    if state.status != ReturnStatus.awaiting_photo:
        # First arrival: record the pause status, then loop back to interrupt.
        attempt = state.photo_retry_count + 1
        return {
            "status": ReturnStatus.awaiting_photo,
            "decision_log": list(state.decision_log)
            + [
                f"photo proof required for damaged/defective claim "
                f"(attempt {attempt}/{settings.MAX_PHOTO_RETRIES})"
            ],
        }

    # Paused pass: interrupt for the client's photo resubmission.
    resume = interrupt({
        "reason": "photo_required",
        "order_id": state.order_id,
        "item_id": state.item_id,
        "attempt": state.photo_retry_count + 1,
        "max_attempts": settings.MAX_PHOTO_RETRIES,
    })
    if not isinstance(resume, dict):
        resume = {"photo_provided": bool(resume)}

    provided = bool(resume.get("photo_provided", False))
    attempt = state.photo_retry_count + 1
    if provided:
        log = (
            f"photo resubmission {attempt}/{settings.MAX_PHOTO_RETRIES}: "
            "proof received"
        )
    else:
        log = (
            f"photo resubmission {attempt}/{settings.MAX_PHOTO_RETRIES}: "
            "no proof provided"
        )
    return {
        "photo_provided": provided,
        "photo_url": resume.get("photo_url"),
        "photo_retry_count": attempt,
        "decision_log": list(state.decision_log) + [log],
    }


def calculate_fee_node(state: ReturnState) -> Dict[str, Any]:
    """Apply the condition-based shipping fee."""
    fee = services.calculate_shipping_fee(state.item_condition)
    return {
        "shipping_fee": fee,
        "decision_log": list(state.decision_log)
        + [
            f"shipping fee ${fee:.2f} applied for condition "
            f"'{state.item_condition.value}'"
        ],
    }


def fraud_check_node(state: ReturnState) -> Dict[str, Any]:
    """Score fraud risk and compute the refund amount."""
    refund_amount = round(state.item_value - state.shipping_fee, 2)
    photo_retries_exhausted = (
        state.item_condition == ItemCondition.damaged_defective
        and not state.photo_provided
        and state.photo_retry_count >= settings.MAX_PHOTO_RETRIES
    )
    score, flags = services.compute_fraud_score(
        customer_id=state.customer_id,
        refund_amount=refund_amount,
        photo_provided=state.photo_provided,
        photo_retries_exhausted=photo_retries_exhausted,
    )
    weight_by_flag = {
        "high_return_velocity": services.VELOCITY_FLAG_WEIGHT,
        "no_photo_proof": services.NO_PHOTO_FLAG_WEIGHT,
        "high_refund_amount": services.HIGH_REFUND_FLAG_WEIGHT,
    }
    breakdown = (
        ", ".join(f"{flag} +{weight_by_flag[flag]:.2f}" for flag in flags)
        if flags
        else "no flags"
    )
    return {
        "refund_amount": refund_amount,
        "fraud_score": score,
        "fraud_flags": flags,
        "decision_log": list(state.decision_log)
        + [
            f"fraud score {score:.2f} ({breakdown}); "
            f"refund amount ${refund_amount:.2f}"
        ],
    }


def human_gate_node(state: ReturnState) -> Dict[str, Any]:
    """Human-approval gate for high-value / risky refunds.

    Pass 1 (first arrival): set ``awaiting_approval`` and loop back.
    Pass 2: ``interrupt()`` until the client resumes with
    ``{"decision": "approve"|"reject", "manager_note": str|None}``.
    Unrecognized/missing decisions fail closed (treated as rejection).
    """
    if state.status != ReturnStatus.awaiting_approval:
        # First arrival: record the pause status + gate triggers, then loop back.
        triggers: List[str] = []
        if state.refund_amount > settings.HIGH_VALUE_THRESHOLD:
            triggers.append(
                f"refund ${state.refund_amount:.2f} > "
                f"${settings.HIGH_VALUE_THRESHOLD:.2f}"
            )
        if state.fraud_score >= settings.FRAUD_SCORE_THRESHOLD:
            triggers.append(
                f"fraud score {state.fraud_score:.2f} >= "
                f"{settings.FRAUD_SCORE_THRESHOLD:.2f}"
            )
        if "no_photo_proof" in state.fraud_flags:
            triggers.append("damaged claim without photo proof")
        trigger_text = "; ".join(triggers) if triggers else "policy"
        return {
            "status": ReturnStatus.awaiting_approval,
            "decision_log": list(state.decision_log)
            + [
                f"manager approval required (refund ${state.refund_amount:.2f}; "
                f"triggered by: {trigger_text})"
            ],
        }

    # Paused pass: interrupt for the manager's decision.
    resume = interrupt({
        "reason": "manager_approval_required",
        "order_id": state.order_id,
        "refund_amount": state.refund_amount,
        "fraud_score": state.fraud_score,
        "fraud_flags": list(state.fraud_flags),
    })
    decision = resume.get("decision") if isinstance(resume, dict) else None
    note = resume.get("manager_note") if isinstance(resume, dict) else None

    if decision == "approve":
        return {
            "status": ReturnStatus.approved,
            "manager_note": note,
            "decision_log": list(state.decision_log) + ["manager approved the refund"],
        }
    # Fail closed: anything that is not an explicit approval is a rejection.
    rejection_log = (
        "manager rejected the refund"
        if decision == "reject"
        else f"unrecognized manager decision '{decision}' — treated as rejection"
    )
    return {
        "status": ReturnStatus.rejected,
        "manager_note": note,
        "decision_log": list(state.decision_log) + [rejection_log],
    }


def finalize_refund_node(state: ReturnState) -> Dict[str, Any]:
    """Call the mock payment gateway and mark the return completed."""
    receipt = services.process_refund(state.order_id, state.refund_amount)
    return {
        "status": ReturnStatus.completed,
        "decision_log": list(state.decision_log)
        + [
            f"refund ${state.refund_amount:.2f} processed successfully "
            f"(txn {receipt['transaction_id']})"
        ],
    }


def reject_policy_node(state: ReturnState) -> Dict[str, Any]:
    """Terminal node for policy denials."""
    return {
        "status": ReturnStatus.denied_policy,
        "decision_log": list(state.decision_log) + ["return denied by policy"],
    }


def reject_by_manager_node(state: ReturnState) -> Dict[str, Any]:
    """Terminal node for manager rejections."""
    return {
        "status": ReturnStatus.rejected,
        "decision_log": list(state.decision_log) + ["return rejected by manager decision"],
    }


# ---------------------------------------------------------------------------
# Conditional edge routers
# ---------------------------------------------------------------------------
def route_after_policy_check(state: ReturnState) -> str:
    """Route to policy rejection or onward to condition classification."""
    if state.status == ReturnStatus.denied_policy:
        return REJECT_POLICY
    return CLASSIFY_CONDITION


def route_after_photo_check(state: ReturnState) -> str:
    """Loop back into the photo node while proof is outstanding, else proceed."""
    needs_photo = (
        state.item_condition == ItemCondition.damaged_defective
        and not state.photo_provided
    )
    if not needs_photo:
        return CALCULATE_FEE
    if state.photo_retry_count >= settings.MAX_PHOTO_RETRIES:
        return CALCULATE_FEE  # exhausted — proceed without proof (fraud flags it)
    return CHECK_PHOTO_PROOF  # cyclical loop: first pass set status, next interrupts


def route_after_fraud_check(state: ReturnState) -> str:
    """Gate on refund value, fraud score, or missing photo proof."""
    unproven_claim = "no_photo_proof" in state.fraud_flags
    if (
        state.refund_amount > settings.HIGH_VALUE_THRESHOLD
        or state.fraud_score >= settings.FRAUD_SCORE_THRESHOLD
        or unproven_claim
    ):
        return HUMAN_GATE
    return FINALIZE_REFUND


def route_after_human_gate(state: ReturnState) -> str:
    """Loop back for the interrupt pass, then route by the manager's decision."""
    if state.status == ReturnStatus.awaiting_approval:
        return HUMAN_GATE  # first pass set the status — next pass interrupts
    if state.status == ReturnStatus.approved:
        return FINALIZE_REFUND
    return REJECT_BY_MANAGER


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
def build_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """Build and compile the return-agent state machine.

    Pass a checkpointer (e.g. :func:`make_sqlite_saver`) to enable durable
    state + ``interrupt()`` resumes keyed by ``thread_id``; omit it for an
    in-memory graph suitable for unit tests.
    """
    builder = StateGraph(ReturnState)

    builder.add_node(VALIDATE_POLICY, validate_policy_node)
    builder.add_node(CLASSIFY_CONDITION, classify_condition_node)
    builder.add_node(CHECK_PHOTO_PROOF, check_photo_proof_node)
    builder.add_node(CALCULATE_FEE, calculate_fee_node)
    builder.add_node(FRAUD_CHECK, fraud_check_node)
    builder.add_node(HUMAN_GATE, human_gate_node)
    builder.add_node(FINALIZE_REFUND, finalize_refund_node)
    builder.add_node(REJECT_POLICY, reject_policy_node)
    builder.add_node(REJECT_BY_MANAGER, reject_by_manager_node)

    builder.add_edge(START, VALIDATE_POLICY)
    builder.add_conditional_edges(
        VALIDATE_POLICY,
        route_after_policy_check,
        {CLASSIFY_CONDITION: CLASSIFY_CONDITION, REJECT_POLICY: REJECT_POLICY},
    )
    builder.add_edge(CLASSIFY_CONDITION, CHECK_PHOTO_PROOF)
    builder.add_conditional_edges(
        CHECK_PHOTO_PROOF,
        route_after_photo_check,
        {CHECK_PHOTO_PROOF: CHECK_PHOTO_PROOF, CALCULATE_FEE: CALCULATE_FEE},
    )
    builder.add_edge(CALCULATE_FEE, FRAUD_CHECK)
    builder.add_conditional_edges(
        FRAUD_CHECK,
        route_after_fraud_check,
        {HUMAN_GATE: HUMAN_GATE, FINALIZE_REFUND: FINALIZE_REFUND},
    )
    builder.add_conditional_edges(
        HUMAN_GATE,
        route_after_human_gate,
        {
            HUMAN_GATE: HUMAN_GATE,
            FINALIZE_REFUND: FINALIZE_REFUND,
            REJECT_BY_MANAGER: REJECT_BY_MANAGER,
        },
    )
    builder.add_edge(FINALIZE_REFUND, END)
    builder.add_edge(REJECT_POLICY, END)
    builder.add_edge(REJECT_BY_MANAGER, END)

    return builder.compile(checkpointer=checkpointer)


#: Default compiled graph instance (no checkpointer) — unit tests & inspection.
graph = build_graph()


# ---------------------------------------------------------------------------
# SQLite checkpointer + thread helpers (used by the API layer in Phase 6)
# ---------------------------------------------------------------------------
def make_serializer() -> JsonPlusSerializer:
    """Serde with an explicit allowlist for this app's checkpointed types.

    LangGraph's default permissive mode deserializes any type and logs a
    deprecation warning for our enums; passing an explicit
    ``allowed_msgpack_modules`` whitelist (``app.schemas`` enums + stdlib safe
    types) removes the warning and locks deserialization down.
    """
    return JsonPlusSerializer(
        allowed_msgpack_modules=(
            (ItemCondition, ReturnStatus),
            ("app.schemas", "ItemCondition"),
            ("app.schemas", "ReturnStatus"),
        )
    )


def make_sqlite_saver(db_path: Optional[str] = None) -> SqliteSaver:
    """Create a long-lived :class:`SqliteSaver` bound to *db_path*.

    ``check_same_thread=False`` so the same saver works across FastAPI's
    request-handling threads and pytest workers.
    """
    path = db_path or settings.SQLITE_DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn, serde=make_serializer())


def thread_config(thread_id: str) -> Dict[str, Any]:
    """LangGraph invocation config carrying the checkpoint *thread_id*."""
    return {"configurable": {"thread_id": thread_id}}


_default_graph: Optional[CompiledStateGraph] = None


def get_default_graph() -> CompiledStateGraph:
    """Lazily-built production graph: SQLite checkpointer at the configured path."""
    global _default_graph
    if _default_graph is None:
        _default_graph = build_graph(make_sqlite_saver())
    return _default_graph


def run_graph(thread_id: str, initial_state: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke the production graph on a fresh *thread_id*.

    Returns the state dict; when the graph pauses, the result carries an
    ``__interrupt__`` key describing the pending gate.
    """
    return get_default_graph().invoke(initial_state, thread_config(thread_id))


def resume_graph(thread_id: str, resume_value: Any) -> Dict[str, Any]:
    """Resume a paused *thread_id* with ``Command(resume=resume_value)``.

    ``resume_value`` must match the shape the paused gate node expects
    (photo loop: ``{"photo_provided": bool, "photo_url": ...}``;
    manager gate: ``{"decision": "approve"|"reject", "manager_note": ...}``).
    """
    return get_default_graph().invoke(
        Command(resume=resume_value), thread_config(thread_id)
    )


def get_state_snapshot(thread_id: str) -> StateSnapshot:
    """Read the latest checkpointed state for *thread_id* (API GET route).

    ``snapshot.next`` is non-empty while the graph is paused at a gate.
    """
    return get_default_graph().get_state(thread_config(thread_id))


def list_thread_ids() -> List[str]:
    """All thread_ids known to the checkpointer, most-recently-updated first.

    Enumerates checkpoints across all threads (``config=None``) and dedupes
    by thread_id, keeping the first sighting of each. The sqlite saver's
    ``list`` orders by ``checkpoint_id DESC`` (newest first per thread), so
    the first sighting is each thread's latest checkpoint.
    """
    seen: List[str] = []
    for checkpoint_tuple in get_default_graph().checkpointer.list(None):
        thread_id = (checkpoint_tuple.config or {}).get(
            "configurable", {}
        ).get("thread_id")
        if thread_id and thread_id not in seen:
            seen.append(thread_id)
    return seen