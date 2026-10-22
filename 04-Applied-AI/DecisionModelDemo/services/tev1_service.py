# Contract discovered by live probe against http://localhost:11434/v1/systemone
# (captured 2026-10-02, saved in docs/samples/tev1_response.json).
#
# Request:  POST {OLLAMA_HOST}/v1/systemone
#           {"model": "<TEV1_MODEL>", "state": "<text>",
#            "questions": {
#                "<question_name>": {
#                    "instructions": "<nonempty string>",
#                    "type": "choice" | "noul" | "score",
#                    "choices": <list of 2-26 option strings>,
#                    "criteria": {"<option>": "<description>"} | null  # same keys as choices
#                }}}
#
# Response: {"model": "<model>",
#            "answers": {"<question_name>": {"type": "choice", "choice": "<option>",
#                         "probabilities": {"<option>": 0.9966, ...},
#                         "confidence": 0.9826}},
#            "usage": {"input_tokens": 153, "output_tokens": 1}}
#
# Notes from probe: questions is an OBJECT keyed by name (not an array);
# "choices" is the option list and "criteria" is the separate description map.
# Server rejects nested malformed shapes with 400 + a plain {"error": ...} body.
# Validation happens server-side before inference: empty questions -> 400
# ("questions must contain 1-64 fields"); criteria not matching choices -> 400
# ("criteria must contain 2-26 candidates"). A model that is not pulled returns
# 404 with {"error":"model '...' not found"} (verified via /api/generate).

import time

import requests

from config.settings import OLLAMA_HOST, TEV1_MODEL, TEV1_TIMEOUT_SECONDS

ENDPOINT_PATH = "/v1/systemone"  # spec section 13: never /api/chat


class Tev1Error(Exception):
    """Typed error with a user-friendly message; never a raw traceback."""


def _friendly_api_error(resp) -> str:
    try:
        return str(resp.json().get("error", resp.text[:200]))
    except ValueError:
        return resp.text[:200]


def call_tev1(state: str, questions: dict) -> dict:
    """Call the Tev1 decision model.

    questions: {name: question-spec dict} per the contract comment above.
    Returns: {"model", "answers", "elapsed_s", and "usage" only when supplied}.
    Raises Tev1Error with an actionable message on failure.
    Never invents fields the API omitted.
    """
    url = f"{OLLAMA_HOST}{ENDPOINT_PATH}"
    payload = {"model": TEV1_MODEL, "state": state, "questions": questions}

    start = time.perf_counter()
    try:
        resp = requests.post(url, json=payload, timeout=TEV1_TIMEOUT_SECONDS)
    except requests.exceptions.ConnectionError:
        raise Tev1Error(
            f"Ollama is not reachable at {OLLAMA_HOST}. Start Ollama, then retry."
        )
    except requests.exceptions.Timeout:
        raise Tev1Error(
            "Tev1 decision model timed out. Try a shorter scenario or restart Ollama."
        )
    except requests.exceptions.RequestException:  # any other transport error
        raise Tev1Error(
            f"Tev1 connection failed ({OLLAMA_HOST}). Check OLLAMA_HOST and your "
            "network, then retry."
        )

    if resp.status_code == 404:
        raise Tev1Error(
            f"Tev1 model '{TEV1_MODEL}' not found. Run: ollama pull {TEV1_MODEL}"
        )
    if resp.status_code != 200:
        raise Tev1Error(
            f"Tev1 request failed (HTTP {resp.status_code}). {_friendly_api_error(resp)}"
        )

    try:
        data = resp.json()
    except ValueError:
        raise Tev1Error("Tev1 returned an invalid (non-JSON) response.")

    answers = data.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise Tev1Error("Tev1 response contained no 'answers' object.")

    result = {"model": data.get("model", TEV1_MODEL), "answers": answers,
              "elapsed_s": round(time.perf_counter() - start, 2)}
    usage = data.get("usage")  # only when supplied — never fabricated
    if isinstance(usage, dict):
        result["usage"] = usage
    return result


if __name__ == "__main__":
    # Self-test: Customer Support sample scenario (spec section 5, mode 1).
    sample_questions = {
        "intent": {
            "instructions": "Pick the customer intent from the choices.",
            "type": "choice",
            "choices": ["duplicate_charge", "cancel_subscription", "card_declined", "none"],
            "criteria": {
                "duplicate_charge": "Customer was billed more than once for the same item",
                "cancel_subscription": "Customer wants to end their subscription",
                "card_declined": "Customer's payment card was rejected",
                "none": "No billing issue applies",
            },
        }
    }
    out = call_tev1("Customer was charged twice for the same subscription.", sample_questions)
    answer = out["answers"]["intent"]
    print(f"Decision:     {answer.get('choice')}")
    print(f"Confidence:   {answer.get('confidence')}")
    print(f"Elapsed:      {out['elapsed_s']} sec")
    print(f"Usage:        {out.get('usage')}")
    print(f"Probabilities: {answer.get('probabilities')}")