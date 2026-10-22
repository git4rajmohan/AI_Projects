# Maintenance pipeline (spec1 §8; plan Phases 6 E). apply_policy owns the
# §6.3 precedence; run_decision wires validate -> rules -> Tev1 -> policy ->
# explanation -> persist -> audit. Tev1 output is evidence; the policy outcome
# is the application decision  Ethey are never conflated (spec1 §10).

from dataclasses import dataclass, field
from typing import Optional

from config.settings import TEV1_CONFIDENCE_REVIEW_THRESHOLD, TREND_WINDOW_READINGS
from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.models import MachineLimits, ValidationResult, validate_reading
from maintai.prompts import Tev1Decision, interpret_tev1
from maintai.rules_engine import RuleReport, evaluate_machine


@dataclass
class PolicyOutcome:
    outcome: str  # the application decision (spec1 §6.3 rungs)
    final_action: str
    human_review_required: bool
    reason: str
    tev1_action: Optional[str] = None

    # Rung names used in the DB + UI.
    DATA_REVIEW = "data_review_required"
    URGENT = "urgent_human_review"
    UNAVAILABLE = "decision_unavailable_review_required"
    REVIEW = "human_review_required"
    AUTO = "policy_auto_decision"


def _accept(tev1: Tev1Decision) -> PolicyOutcome:
    action = tev1.action or "insufficient_data"
    return PolicyOutcome(PolicyOutcome.AUTO, action,
                         action == "urgent_maintenance",
                         f"Tev1 classification '{action}' accepted", tev1.action)


def apply_policy(validation: ValidationResult,
                 report: RuleReport,
                 tev1: Optional[Tev1Decision],
                 confidence_threshold: float = TEV1_CONFIDENCE_REVIEW_THRESHOLD
                 ) -> PolicyOutcome:
    """Deterministic precedence ladder (spec1 §6.3, in order). Hard rules beat
    the model; a failed model call never becomes a safe decision (spec1 §14)."""
    if not validation.ok:
        return PolicyOutcome(  # 1. invalid / stale / missing data
            PolicyOutcome.DATA_REVIEW,
            "insufficient_data", True,
            "; ".join(validation.reasons) or "Input data failed validation")

    if report.mandatory_escalation:  # 2. configured safety escalation
        return PolicyOutcome(PolicyOutcome.URGENT, "urgent_maintenance", True,
                             "Machine policy mandates human escalation")

    if report.critical_breaches:  # 3. critical threshold overrides any monitor
        channels = ", ".join(report.critical_breaches)
        return PolicyOutcome(PolicyOutcome.URGENT, "urgent_maintenance", True,
                             f"Critical engineering threshold exceeded: {channels}")

    if tev1 is None or tev1.action is None:  # 4. model failed / invalid
        return PolicyOutcome(PolicyOutcome.UNAVAILABLE, "insufficient_data", True,
                             "Tev1 decision unavailable or invalid")

    if tev1.action == "insufficient_data":
        return PolicyOutcome(PolicyOutcome.REVIEW, "insufficient_data", True,
                             "Tev1 reported insufficient evidence")

    confidence = tev1.action_confidence
    # monitor + anomaly evidence contradiction; rung 3 already removed criticals
    contradicts = (
        tev1.action == "monitor"
        and tev1.anomaly_probability is not None
        and tev1.anomaly_probability > 0.5
    )
    if contradicts or (  # 5. low confidence / conflicting evidence
        isinstance(confidence, (int, float))
        and confidence < confidence_threshold
    ):
        reason = ("Tev1 'monitor' conflicts with anomaly evidence"
                  if contradicts else
                  f"Confidence {confidence:.2f} below review threshold "
                  f"{confidence_threshold:.2f}")
        return PolicyOutcome(PolicyOutcome.REVIEW, "insufficient_data", True, reason)

    return _accept(tev1)  # 6. otherwise the configured classification applies


# ----------------------------------------------------------------- pipeline --

def _limit_dict(limits_row) -> dict:
    """Active-limits DB row -> {'temperature': {warning, critical}, ...}."""
    return {
        "temperature": {"warning": limits_row["temperature_warning"],
                        "critical": limits_row["temperature_critical"]},
        "vibration": {"warning": limits_row["vibration_warning"],
                      "critical": limits_row["vibration_critical"]},
        "motor_load": {"warning": limits_row["motor_load_warning"],
                       "critical": limits_row["motor_load_critical"]},
    }


@dataclass
class DecisionRecord:
    machine_id: str
    outcome: PolicyOutcome
    validation: ValidationResult
    report: RuleReport
    tev1: Optional[Tev1Decision]
    explanation: Optional[dict] = None      # LLM payload (Phase 8)
    explanation_error: Optional[str] = None
    decision_id: Optional[int] = None
    error_status: Optional[str] = None


def run_decision(machine_id: str, conn, user_id: str = "dashboard",
                 run_tev1=None, run_llm=None) -> DecisionRecord:
    """Full workflow for one machine (spec1 §8 steps 1–9), persisting the
    decision + audit rows. run_tev1/run_llm are injectable callables for tests;
    None = the real services. A Tev1 failure is persisted as a review-required
    decision — never silently converted into a safe outcome (spec1 §14).
    Settings page session overrides (tuning.tuning()) supply the confidence
    threshold + freshness window; .env defaults otherwise (plan 14.3)."""
    from maintai import prompts as tev1_prompts
    from maintai.tuning import tuning as session_tuning
    from services.tev1_service import Tev1Error, call_tev1

    confidence_threshold, freshness_minutes = session_tuning()

    machine = repo.get_machine(conn, machine_id)
    if machine is None:
        raise ValueError(f"Unknown machine '{machine_id}'. Register it first.")

    row = repo.latest_reading(conn, machine_id)
    if row is None:
        raise ValueError(f"No sensor readings stored for '{machine_id}'. "
                         "Import data or run the seed script.")

    limits_row = repo.active_limits(conn, machine_id)
    if limits_row is None:
        raise ValueError(f"No configured limits for '{machine_id}'. "
                         "Set them on the Machine Registry page.")
    limit_dict = _limit_dict(limits_row)
    limits = MachineLimits(**{k: limits_row[k] for k in repo.LIMIT_FIELDS})

    reading_input = {
        **{k: row[k] for k in row.keys() if k not in ("id", "validation_status")},
        "machine_type": machine["machine_type"],
    }
    history_raw = repo.readings_window(conn, machine_id,
                                       limit=TREND_WINDOW_READINGS + 1)
    validation = validate_reading(reading_input, limits, freshness_minutes)
    if not validation.ok:
        record = DecisionRecord(machine_id, apply_policy(validation, RuleReport(),
                                                         None), validation,
                                RuleReport(), None, error_status=validation.status)
        _persist(conn, record, limits_row["version"], None, user_id)
        return record

    reading = validation.reading
    history = []
    for history_row in history_raw:
        history_validation = validate_reading({
            **{k: history_row[k] for k in history_row.keys()
               if k not in ("id", "validation_status")},
            "machine_type": machine["machine_type"],
        }, limits=None, freshness_minutes=0)
        if history_validation.status == "invalid":
            validation = ValidationResult(
                "invalid", ["Historical sensor reading is invalid: "
                            + "; ".join(history_validation.reasons)])
            record = DecisionRecord(
                machine_id, apply_policy(validation, RuleReport(), None),
                validation, RuleReport(), None,
                error_status="validation_failed: invalid historical reading")
            _persist(conn, record, limits_row["version"], None, user_id)
            return record
        if history_validation.reading:
            history.append(history_validation.reading)

    values = {c: getattr(reading, c) for c in ("temperature_c", "vibration_mm_s",
                                               "motor_load_percent", "rpm")}
    report_eval = evaluate_machine(
        reading, limits, history,
        mandatory_escalation=machine["status"] == "mandatory_escalation")

    tev1 = None
    error_status = None
    if run_tev1 is None:
        run_tev1 = call_tev1
    try:
        request = tev1_prompts.decision_request(report_eval, values, limit_dict)
        tev1 = interpret_tev1(run_tev1(request["state"], request["questions"]))
        if tev1.action not in tev1_prompts.ACTIONS:
            raise ValueError("missing or unknown maintenance action")
    except Tev1Error as exc:
        error_status = f"decision_unavailable: {exc}"
    except (AttributeError, TypeError, ValueError):
        error_status = "decision_unavailable: Tev1 returned an invalid response."

    outcome = apply_policy(validation, report_eval, tev1,
                           confidence_threshold=confidence_threshold)
    record = DecisionRecord(machine_id, outcome, validation, report_eval,
                            tev1, error_status=error_status)
    # Explanation runs after the policy outcome exists (the LLM explains, never
    # decides). Real service by default; run_llm=False skips (tests/offline).
    if run_llm is not False:
        if run_llm:
            record.explanation, record.explanation_error = run_llm(record)
        else:
            from maintai import explanation_service
            history_lines = [f"{r['inspection_date']} — {r['findings']}"
                             for r in repo.list_inspections(conn, machine_id)[:3]]
            record.explanation, record.explanation_error = (
                explanation_service.generate_explanation(
                    record, values, limit_dict, history_lines))
    if record.explanation_error:
        record.error_status = (record.error_status + "; "
                               if record.error_status else "")
        record.error_status += "llm_explanation_unavailable"
    _persist(conn, record, limits_row["version"], limit_dict, user_id)
    return record


def record_inspection(conn, machine_id: str, decision_id: int,
                      inspection: dict, role: str) -> int:
    """Record a human review; the prototype role gate is not authentication."""
    if role not in ("Engineer", "Administrator"):
        raise PermissionError("Engineer or Administrator role is required.")
    inspector = inspection.get("inspector", "").strip()
    findings = inspection.get("findings", "").strip()
    status = inspection.get("resolution_status")
    if not inspector or not findings:
        raise ValueError("Inspector and findings are required.")
    if status not in ("open", "closed"):
        raise ValueError("Resolution status must be open or closed.")
    if not repo.decision_belongs_to_machine(conn, machine_id, decision_id):
        raise ValueError("The selected decision does not belong to this machine.")

    with conn:
        inspection_id = repo.insert_inspection(conn, {
            **inspection, "machine_id": machine_id,
            "inspector": inspector, "findings": findings,
        })
        repo.record_audit(
            conn, inspector, "inspection_recorded", "machine", machine_id,
            {"inspection_id": inspection_id, "decision_id": decision_id,
             "resolution_status": status, "reviewer_role": role})
    return inspection_id


def _persist(conn, record: DecisionRecord, policy_version, limit_dict,
             user_id: str) -> None:
    """Persist the decision + audit entry for every path, including failures."""
    snapshot = (record.validation.reading.model_dump(mode="json")
                if record.validation.reading else
                {"machine_id": record.machine_id})
    snapshot["limits"] = limit_dict or {}
    tev1 = record.tev1
    with conn:
        decision_id = repo.insert_decision(conn, {
            "machine_id": record.machine_id,
            "input_snapshot": snapshot,
            "rule_alerts": record.report.alerts,
            "tev1_action": tev1.action if tev1 else None,
            "tev1_probabilities": tev1.action_probabilities if tev1 else None,
            "tev1_confidence": tev1.action_confidence if tev1 else None,
            "policy_outcome": record.outcome.outcome,
            "llm_explanation": record.explanation,
            "model_name": tev1.model if tev1 else None,
            "policy_version": str(policy_version),
            "latency_ms": (tev1.elapsed_s * 1000) if tev1 and tev1.elapsed_s else None,
            "error_status": record.error_status,
        })
        repo.record_audit(conn, user_id, "decision_recorded", "machine",
                          record.machine_id, {"decision_id": decision_id,
                                              "outcome": record.outcome.outcome})
    record.decision_id = decision_id


if __name__ == "__main__":
    # Self-test (plan 7.4): offline canned Tev1 response, live when RUN_LIVE_TESTS=1.
    import os

    canned = {"model": "tev1:4b", "elapsed_s": 0.9, "answers": {
        "maintenance_action": {"type": "choice", "choice": "inspect",
                               "probabilities": {"inspect": 0.8, "monitor": 0.2},
                               "confidence": 0.8},
        "anomaly_present": {"type": "noul", "noul": 0.9},
        "severity": {"type": "score", "score": 2.4,
                     "legend": {"0": "Normal", "1": "Low", "2": "Moderate",
                                "3": "High", "4": "Critical"},
                     "probabilities": {"2": 0.6, "3": 0.4}, "confidence": 0.7},
    }}
    conn = get_conn()
    init_db(conn)
    for machine in repo.list_machines(conn):
        record = run_decision(machine["machine_id"], conn,
                              run_tev1=(lambda s, q: canned)
                              if os.getenv("RUN_LIVE_TESTS") != "1" else None)
        print(f"{record.machine_id}: {record.outcome.outcome} "
              f"-> {record.outcome.final_action} "
              f"(alerts: {len(record.report.alerts)}, "
              f"confidence: {record.tev1.action_confidence if record.tev1 else None})")
    conn.close()
    print("OK")
