"""
LangGraph pipeline for ticket classification.

Each node delegates to a production module — no LLM wiring lives here.

Node order: pii_redact → injection_check → classify → validate → cost_log
                                                  ↓ (fail)
                                              fallback → cost_log
"""

import logging
import os
import time

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from schema import TicketClassification
from production_modules.pii_redaction import redact_pii
from production_modules.prompt_injection import check_injection
from production_modules.prompt_versioning import get_active_prompt, get_active_version
from production_modules.structured_output import classify_with_json_mode
from production_modules.validate_response import validate_classification
from production_modules.cost_calculator import calculate_cost, count_tokens
from production_modules.fallback_retry import classify_with_fallback, SAFE_CLASSIFICATION

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss:120b")


# ---------------------------------------------------------------------------
# Node: pii_redact
# ---------------------------------------------------------------------------
def pii_redact_node(state: dict) -> dict:
    result = redact_pii(state["raw_ticket"])
    print(result)
    return {
        **state,
        "redacted_ticket": result.redacted_text,
        "pii_detected": result.pii_detected,
        "pii_entity_types": result.detected_entity_types,
    }


# ---------------------------------------------------------------------------
# Node: injection_check
# ---------------------------------------------------------------------------
def injection_check_node(state: dict) -> dict:
    check = check_injection(state["raw_ticket"])
    if not check.is_safe:
        logger.warning("Injection detected: %s", check.detected_pattern)
        return {
            **state,
            "injection_blocked": True,
            "injection_pattern": check.detected_pattern,
            "error": f"Injection detected: {check.detected_pattern}",
            "classification": SAFE_CLASSIFICATION,
            "validation_status": "blocked",
        }
    return {**state, "injection_blocked": False, "injection_pattern": None}


# ---------------------------------------------------------------------------
# Node: classify
# ---------------------------------------------------------------------------
def classify_node(state: dict) -> dict:
    if state.get("injection_blocked"):
        return state

    active = get_active_prompt()
    version = get_active_version()
    ticket_text = state.get("redacted_ticket") or state["raw_ticket"]

    try:
        classification = classify_with_json_mode(
            ticket_text=ticket_text,
            system_prompt=active["template"],
            model=DEFAULT_MODEL,
        )
        return {**state, "classification": classification, "prompt_version": version}
    except Exception as exc:
        logger.error("classify_node failed: %s", exc)
        return {**state, "error": str(exc), "classification": None, "prompt_version": version}


# ---------------------------------------------------------------------------
# Node: validate
# ---------------------------------------------------------------------------
def validate_node(state: dict) -> dict:
    if state.get("injection_blocked"):
        return state

    raw = state.get("classification")
    if raw is None:
        return {**state, "validation_status": "fail"}

    result = validate_classification(raw)
    return {
        **state,
        "validation_status": "pass" if result.is_valid else "fail",
        "error": None if result.is_valid else "; ".join(result.error_details),
        "classification": result.validated_classification if result.is_valid else raw,
    }


# ---------------------------------------------------------------------------
# Node: fallback
# ---------------------------------------------------------------------------
def fallback_node(state: dict) -> dict:
    logger.warning("Entering fallback node — delegating to classify_with_fallback")
    ticket_text = state.get("redacted_ticket") or state["raw_ticket"]

    classification = classify_with_fallback(ticket_text=ticket_text, model=DEFAULT_MODEL)
    validation_status = "pass" if classification.confidence_score > 0.0 else "fallback_safe"

    return {
        **state,
        "classification": classification,
        "validation_status": validation_status,
    }


# ---------------------------------------------------------------------------
# Node: cost_log
# ---------------------------------------------------------------------------
def cost_log_node(state: dict) -> dict:
    ticket_text = state.get("redacted_ticket") or state["raw_ticket"]
    classification = state.get("classification")

    input_tokens = count_tokens(ticket_text, DEFAULT_MODEL)
    output_tokens = count_tokens(
        classification.model_dump_json() if classification else "", DEFAULT_MODEL
    )
    cost_info = calculate_cost(DEFAULT_MODEL, input_tokens, output_tokens)

    if os.getenv("LOG_COSTS", "true").lower() == "true":
        logger.info(
            "Cost — model: %s | in: %d | out: %d | total: $%.6f",
            cost_info.model,
            cost_info.input_tokens,
            cost_info.output_tokens,
            cost_info.total_cost_usd,
        )

    return {
        **state,
        "cost_info": {
            "model": cost_info.model,
            "input_tokens": cost_info.input_tokens,
            "output_tokens": cost_info.output_tokens,
            "total_cost_usd": cost_info.total_cost_usd,
        },
    }


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------
def route_after_validate(state: dict) -> str:
    if state.get("injection_blocked"):
        return "cost_log"
    if state.get("validation_status") == "pass":
        return "cost_log"
    return "fallback"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------
def build_graph():
    builder = StateGraph(dict)

    builder.add_node("pii_redact", pii_redact_node)
    builder.add_node("injection_check", injection_check_node)
    builder.add_node("classify", classify_node)
    builder.add_node("validate", validate_node)
    builder.add_node("fallback", fallback_node)
    builder.add_node("cost_log", cost_log_node)

    builder.add_edge(START, "pii_redact")
    builder.add_edge("pii_redact", "injection_check")
    builder.add_edge("injection_check", "classify")
    builder.add_edge("classify", "validate")
    builder.add_conditional_edges("validate", route_after_validate, {
        "cost_log": "cost_log",
        "fallback": "fallback",
    })
    builder.add_edge("fallback", "cost_log")
    builder.add_edge("cost_log", END)

    return builder.compile()


graph = build_graph()


def run_pipeline(ticket_text: str, channel: str = "web_form") -> dict:
    initial_state = {
        "raw_ticket": ticket_text,
        "channel": channel,
        "redacted_ticket": None,
        "classification": None,
        "validation_status": None,
        "cost_info": None,
        "error": None,
        "pii_detected": False,
        "prompt_version": None,
        "injection_blocked": False,
    }
    return graph.invoke(initial_state)


# ---------------------------------------------------------------------------
# Traced execution — per-node status/duration/output for the workflow UI
# ---------------------------------------------------------------------------
NODE_LABELS = {
    "pii_redact": "PII Redact",
    "injection_check": "Injection Check",
    "classify": "Classify",
    "validate": "Validate",
    "fallback": "Fallback",
    "cost_log": "Cost Log",
}

_DISPLAY_ORDER = list(NODE_LABELS)


def _serialize_classification(value):
    """Convert a TicketClassification (or None) into a plain dict for JSON."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _node_status(name: str, delta: dict) -> str:
    """Classify a node's state delta as success | failed | skipped."""
    if name == "injection_check":
        return "failed" if delta.get("injection_blocked") else "success"
    if name == "classify":
        if delta.get("injection_blocked"):
            return "skipped"
        if delta.get("classification") is None or delta.get("error"):
            return "failed"
        return "success"
    if name == "validate":
        if delta.get("injection_blocked"):
            return "skipped"
        return "success" if delta.get("validation_status") == "pass" else "failed"
    return "success"


def _node_output(name: str, delta: dict) -> dict:
    """Curate the per-node detail payload shown in the UI drawer."""
    if name == "pii_redact":
        return {
            "redacted_text": delta.get("redacted_ticket"),
            "pii_detected": delta.get("pii_detected"),
            "entity_types": delta.get("pii_entity_types") or [],
        }
    if name == "injection_check":
        blocked = bool(delta.get("injection_blocked"))
        return {
            "is_safe": not blocked,
            "detected_pattern": delta.get("injection_pattern"),
        }
    if name == "classify":
        return {
            "classification": _serialize_classification(delta.get("classification")),
            "prompt_version": delta.get("prompt_version"),
            "error": delta.get("error"),
        }
    if name == "validate":
        return {
            "validation_status": delta.get("validation_status"),
            "error": delta.get("error"),
            "classification": _serialize_classification(delta.get("classification")),
        }
    if name == "fallback":
        return {
            "classification": _serialize_classification(delta.get("classification")),
            "validation_status": delta.get("validation_status"),
        }
    if name == "cost_log":
        return {"cost_info": delta.get("cost_info")}
    return {}


def run_pipeline_traced(ticket_text: str, channel: str = "web_form") -> tuple[dict, list]:
    """
    Run the pipeline exactly like run_pipeline, but additionally collect a
    per-node trace (status, duration_ms, curated output) for the workflow UI.

    Uses graph.stream(stream_mode="updates") so each node's state delta is
    captured as it completes. Nodes that never execute (e.g. fallback on a
    clean run) are reported as "skipped" so the UI can render them grey.
    """
    initial_state = {
        "raw_ticket": ticket_text,
        "channel": channel,
        "redacted_ticket": None,
        "classification": None,
        "validation_status": None,
        "cost_info": None,
        "error": None,
        "pii_detected": False,
        "pii_entity_types": [],
        "prompt_version": None,
        "injection_blocked": False,
        "injection_pattern": None,
    }

    started = time.perf_counter()
    last_ts = started
    node_updates: dict[str, tuple[dict, int]] = {}
    final_state: dict = dict(initial_state)

    for chunk in graph.stream(initial_state, stream_mode="updates"):
        now = time.perf_counter()
        if not isinstance(chunk, dict):
            continue
        for node_name, delta in chunk.items():
            if node_name not in NODE_LABELS or not isinstance(delta, dict):
                continue
            node_updates[node_name] = (delta, round((now - last_ts) * 1000))
            final_state.update(delta)
        last_ts = now

    trace = []
    for name in _DISPLAY_ORDER:
        if name in node_updates:
            delta, duration_ms = node_updates[name]
            trace.append({
                "node": name,
                "label": NODE_LABELS[name],
                "status": _node_status(name, delta),
                "duration_ms": duration_ms,
                "output": _node_output(name, delta),
            })
        else:
            trace.append({
                "node": name,
                "label": NODE_LABELS[name],
                "status": "skipped",
                "duration_ms": 0,
                "output": None,
            })

    return final_state, trace
