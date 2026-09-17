"""FastAPI layer for the return agent (Phase 6).

Routes (plan.md API surface):

- ``POST /returns``                       — start a return workflow (new thread_id)
- ``POST /returns/{thread_id}/photo``     — resume the photo-proof interrupt loop
- ``POST /returns/{thread_id}/approve``   — resume the manager gate with approval
- ``POST /returns/{thread_id}/reject``    — resume the manager gate with rejection
- ``GET  /returns/{thread_id}``           — inspect the checkpointed run state

Error semantics:

- 404 when ``thread_id`` is unknown (never checkpointed).
- 409 when resuming a thread that is not paused, or paused at the wrong gate.
- 422 (FastAPI default) when the request body fails validation.

Run locally (from the ``return-agent/`` directory)::

    uvicorn app.main:app --reload
"""
import uuid
from typing import Any, Dict, List, Mapping, Optional, Tuple

from fastapi import FastAPI, HTTPException

from app.graph import (
    CHECK_PHOTO_PROOF,
    HUMAN_GATE,
    get_state_snapshot,
    list_thread_ids,
    resume_graph,
    run_graph,
)
from app.schemas import (
    ApprovalRequest,
    OrderSummary,
    PhotoResubmitRequest,
    ReturnRequest,
    ReturnResponse,
    ReturnState,
    ReturnStatus,
)
from app.services import MOCK_ORDERS

app = FastAPI(
    title="E-Commerce Return & Fraud Prevention Agent",
    description=(
        "LangGraph-backed return/refund workflow with a cyclical photo-proof "
        "loop, deterministic fraud heuristics, and SQLite-checkpointed "
        "human-in-the-loop approval gates."
    ),
    version="1.0.0",
)

#: Statuses at/after the fraud check — fee/fraud/refund fields are computed.
_COMPUTED_STATUSES = frozenset(
    {
        ReturnStatus.awaiting_approval,
        ReturnStatus.approved,
        ReturnStatus.completed,
        ReturnStatus.rejected,
    }
)

#: status -> (client-facing message, next action for the caller).
_STATUS_META: Dict[ReturnStatus, Tuple[str, str]] = {
    ReturnStatus.pending: ("Return received and queued for processing.", "none"),
    ReturnStatus.awaiting_photo: (
        "Damaged/defective claim requires photo proof before the refund can be processed.",
        "submit_photo",
    ),
    ReturnStatus.awaiting_approval: (
        "Refund requires manager approval (high value or fraud flags).",
        "await_manager",
    ),
    ReturnStatus.approved: ("Manager approved the refund; payment is being finalized.", "none"),
    ReturnStatus.completed: ("Return completed — refund processed successfully.", "none"),
    ReturnStatus.rejected: ("Return rejected by manager decision; no refund issued.", "none"),
    ReturnStatus.denied_policy: (
        "Return denied by policy: order unknown or outside the 30-day return window.",
        "none",
    ),
}


def _response_from_state(thread_id: str, values: Mapping[str, Any]) -> ReturnResponse:
    """Build a :class:`ReturnResponse` from checkpointed graph state.

    The raw checkpoint values may omit channels no node has written yet, so
    the state is normalized through :class:`ReturnState` first. Identifiers
    (order/item/reason) are always populated so list views can identify a
    return without a second lookup; fee/fraud/refund fields are only exposed
    once the workflow has passed the fraud check (they would be misleading
    0.0 defaults before that point).
    """
    state = ReturnState.model_validate(dict(values))
    message, next_action = _STATUS_META[state.status]

    fields: Dict[str, Any] = {
        "order_id": state.order_id,
        "item_id": state.item_id,
        "reason_text": state.reason_text,
        "item_condition": state.item_condition.value,
        "decision_log": list(state.decision_log),
    }
    if state.status in _COMPUTED_STATUSES:
        fields.update(
            {
                "refund_amount": state.refund_amount,
                "shipping_fee": state.shipping_fee,
                "fraud_score": state.fraud_score,
                "fraud_flags": list(state.fraud_flags),
            }
        )
    if state.manager_note:
        fields["manager_note"] = state.manager_note

    return ReturnResponse(
        thread_id=thread_id,
        status=state.status,
        message=message,
        next_action=next_action,
        **fields,
    )


def _load_snapshot_or_404(thread_id: str):
    """Fetch the checkpointed snapshot for *thread_id* or raise 404.

    A thread that was never checkpointed yields an empty ``values`` dict.
    """
    snapshot = get_state_snapshot(thread_id)
    if not snapshot.values:
        raise HTTPException(
            status_code=404,
            detail=f"No return found for thread '{thread_id}'.",
        )
    return snapshot


def _paused_gate(snapshot) -> str | None:
    """Name of the node the graph is paused inside, or ``None`` when finished."""
    return snapshot.next[0] if snapshot.next else None


def _resume_at_gate(
    thread_id: str,
    expected_gate: str,
    resume_value: Any,
    not_paused_detail: str,
    wrong_gate_detail: str,
) -> ReturnResponse:
    """Resume a paused thread at *expected_gate* or raise 409.

    409 covers both "not paused at all" (run finished) and "paused at the
    wrong gate" (e.g. posting a photo to a thread awaiting manager approval).
    """
    snapshot = _load_snapshot_or_404(thread_id)
    gate = _paused_gate(snapshot)
    if gate is None:
        raise HTTPException(status_code=409, detail=not_paused_detail)
    if gate != expected_gate:
        raise HTTPException(
            status_code=409, detail=wrong_gate_detail.format(gate=gate)
        )
    resume_graph(thread_id, resume_value)
    return _response_from_state(thread_id, get_state_snapshot(thread_id).values)


@app.post("/returns", response_model=ReturnResponse)
def create_return(payload: ReturnRequest) -> ReturnResponse:
    """Start a return workflow on a fresh thread_id.

    Depending on policy/classification/value the run either completes,
    pauses awaiting a photo, pauses awaiting manager approval, or is denied
    by policy — the returned status says which.
    """
    thread_id = str(uuid.uuid4())
    try:
        run_graph(thread_id, payload.model_dump())
    except Exception as exc:  # pragma: no cover — defensive
        raise HTTPException(
            status_code=500, detail=f"return workflow failed: {exc}"
        ) from exc
    return _response_from_state(thread_id, get_state_snapshot(thread_id).values)


@app.post("/returns/{thread_id}/photo", response_model=ReturnResponse)
def submit_photo(thread_id: str, payload: PhotoResubmitRequest) -> ReturnResponse:
    """Resume the photo-proof interrupt loop with a (new) photo answer.

    Resuming with ``photo_provided=false`` re-pauses the loop (bounded by
    ``MAX_PHOTO_RETRIES``); once retries are exhausted the run proceeds and
    the fraud check flags the unproven claim.
    """
    return _resume_at_gate(
        thread_id,
        expected_gate=CHECK_PHOTO_PROOF,
        resume_value={
            "photo_provided": payload.photo_provided,
            "photo_url": payload.photo_url,
        },
        not_paused_detail="Return is not paused — there is no photo proof pending.",
        wrong_gate_detail=(
            "Return is paused at '{gate}', not awaiting photo proof."
        ),
    )


@app.post("/returns/{thread_id}/approve", response_model=ReturnResponse)
def approve_return(thread_id: str, payload: ApprovalRequest) -> ReturnResponse:
    """Resume the manager-approval gate with ``decision=approve``."""
    return _resume_at_gate(
        thread_id,
        expected_gate=HUMAN_GATE,
        resume_value={"decision": "approve", "manager_note": payload.manager_note},
        not_paused_detail="Return is not awaiting manager approval.",
        wrong_gate_detail=(
            "Return is paused at '{gate}', not awaiting manager approval."
        ),
    )


@app.post("/returns/{thread_id}/reject", response_model=ReturnResponse)
def reject_return(thread_id: str, payload: ApprovalRequest) -> ReturnResponse:
    """Resume the manager-approval gate with ``decision=reject``."""
    return _resume_at_gate(
        thread_id,
        expected_gate=HUMAN_GATE,
        resume_value={"decision": "reject", "manager_note": payload.manager_note},
        not_paused_detail="Return is not awaiting manager approval.",
        wrong_gate_detail=(
            "Return is paused at '{gate}', not awaiting manager approval."
        ),
    )


@app.get("/returns/{thread_id}", response_model=ReturnResponse)
def get_return(thread_id: str) -> ReturnResponse:
    """Inspect the current checkpointed state of a return workflow."""
    snapshot = _load_snapshot_or_404(thread_id)
    return _response_from_state(thread_id, snapshot.values)


@app.get("/orders", response_model=List[OrderSummary])
def list_orders() -> List[OrderSummary]:
    """List the seeded mock orders (drives the UI's order picker)."""
    return [
        OrderSummary(
            order_id=o["order_id"],
            item_id=o["item_id"],
            item_name=o["item_name"],
            item_value=o["item_value"],
            order_date=o["order_date"],
        )
        for o in MOCK_ORDERS.values()
    ]


@app.get("/returns", response_model=List[ReturnResponse])
def list_returns(status: Optional[ReturnStatus] = None) -> List[ReturnResponse]:
    """List all returns known to the checkpointer, newest-thread first.

    ``?status=...`` filters by lifecycle status (e.g. the manager queue's
    ``awaiting_approval``). Threads with an empty checkpoint (shouldn't
    happen in practice) are skipped defensively.
    """
    out: List[ReturnResponse] = []
    for thread_id in list_thread_ids():
        snapshot = get_state_snapshot(thread_id)
        if not snapshot.values:
            continue
        response = _response_from_state(thread_id, snapshot.values)
        if status is None or response.status == status:
            out.append(response)
    return out


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)