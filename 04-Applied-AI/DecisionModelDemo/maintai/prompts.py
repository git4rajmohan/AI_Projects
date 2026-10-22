# Tev1 maintenance prompts + decision parsing (spec1 §5.3–5.5, plan Phase 5).
# Request/answer shapes per the live probe (docs/samples/maintenance_tev1_response.json):
#   choice -> {choice, probabilities{}, confidence}; score -> {score, legend{},
#   probabilities{}, confidence}; noul -> {noul: prob}. Nothing is fabricated:
#   absent fields stay None.

from dataclasses import dataclass, field
from typing import Optional

from maintai.rules_engine import RuleReport

ACTIONS = ["monitor", "inspect", "urgent_maintenance", "insufficient_data"]

QUESTIONS = {
    "maintenance_action": {
        "type": "choice",
        "instructions": (
            "Classify the machine maintenance action based on the supplied "
            "sensor evidence and engineering rule alerts."
        ),
        "choices": ACTIONS,
        "criteria": {
            "monitor": (
                "Continue monitoring under the approved operating policy, "
                "with no escalation required."
            ),
            "inspect": (
                "Arrange a timely inspection because abnormal conditions "
                "require investigation."
            ),
            "urgent_maintenance": (
                "Escalate urgently for qualified maintenance review because "
                "multiple serious abnormalities are present."
            ),
            "insufficient_data": (
                "Evidence is insufficient or unreliable to make a defensible "
                "classification."
            ),
        },
    },
    "anomaly_present": {
        "type": "noul",
        "instructions": (
            "Do the supplied sensor readings or engineering rule alerts "
            "indicate an abnormal condition?"
        ),
    },
    "severity": {
        "type": "score",
        "instructions": (
            "Assess the severity of the supplied machine condition, "
            "considering the rule alerts and sensor deviations."
        ),
        "choices": ["Normal", "Low", "Moderate", "High", "Critical"],
        "criteria": [
            "Negligible abnormality",
            "Minor abnormality",
            "Moderate abnormality",
            "Serious abnormality",
            "Immediate safety concern",
        ],
    },
}

# state text labels/units per channel; limits dict is {'temperature': {warning,
# critical}, ...} — the shape the repository's active-limit row maps to.
_STATE_LABELS = (("temperature_c", "Temperature", "C"),
                 ("vibration_mm_s", "Vibration", "mm/s"),
                 ("motor_load_percent", "Motor load", "%"),
                 ("rpm", "Speed", "rpm"))
_LIMIT_KEYS = {"temperature_c": "temperature", "vibration_mm_s": "vibration",
               "motor_load_percent": "motor_load", "rpm": None}


def build_state(report: RuleReport, values: dict, limits: dict) -> str:
    """Concise machine state TEXT for Tev1 (probed contract: state is a string).
    values: validated channel values; limits: {'temperature': {warning,
    critical}, ...}."""
    lines = ["Machine sensor evidence:"]
    for channel, label, unit in _STATE_LABELS:
        value = values.get(channel)
        if value is None:
            lines.append(f"- {label}: not reported")
            continue
        lim = limits.get(_LIMIT_KEYS[channel]) or {}
        warn, crit = lim.get("warning"), lim.get("critical")
        line = f"- {label}: {value:g} {unit}"
        if warn is not None:
            line += f" (warning {warn:g} {unit}, critical {crit:g} {unit})"
        lines.append(line)
    lines.append("Trends: " + (", ".join(
        f"{name} {trend}" for name, trend in report.trends.items() if trend
    ) or "not enough history"))
    lines.append("Rule alerts: " + ("; ".join(report.alerts) if report.alerts
                                    else "none"))
    return "\n".join(lines)


@dataclass
class Tev1Decision:
    action: Optional[str] = None
    action_probabilities: dict = field(default_factory=dict)
    action_confidence: Optional[float] = None
    anomaly_probability: Optional[float] = None
    severity_score: Optional[float] = None
    severity_label: Optional[str] = None
    model: Optional[str] = None
    elapsed_s: Optional[float] = None


def interpret_tev1(result: dict) -> Tev1Decision:
    """Typed parse of the 3-question maintenance answer set.
    Never invents fields the API omitted."""
    answers = result.get("answers") or {}
    decision = Tev1Decision(model=result.get("model"),
                            elapsed_s=result.get("elapsed_s"))

    action = answers.get("maintenance_action") or {}
    if action.get("type") == "choice":
        decision.action = action.get("choice")
        probs = action.get("probabilities")
        decision.action_probabilities = dict(probs) if isinstance(probs, dict) else {}
        decision.action_confidence = action.get("confidence")

    anomaly = answers.get("anomaly_present") or {}
    noul = anomaly.get("noul")
    if isinstance(noul, (int, float)):
        decision.anomaly_probability = noul

    severity = answers.get("severity") or {}
    if severity.get("type") == "score":
        score = severity.get("score")
        if isinstance(score, (int, float)):
            decision.severity_score = score
            decision.severity_label = (severity.get("legend") or {}).get(str(int(score)))
    return decision


def decision_request(report: RuleReport, values: dict, limits: dict) -> dict:
    """The {state, questions} pair for services.tev1_service.call_tev1."""
    return {"state": build_state(report, values, limits), "questions": QUESTIONS}