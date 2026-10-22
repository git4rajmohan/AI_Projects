# Contract from live probe (2026-10-02, sample in docs/samples/llm_response.json):
# POST {OLLAMA_CLOUD_HOST}/api/chat  Authorization: Bearer <OLLAMA_API_KEY>
#   {"model": "<OLLAMA_CLOUD_MODEL>", "messages": [{"role": "user", "content": ...}], "stream": false}
# Response: {"model", "message": {"role": "assistant", "content": "...", "thinking": "..."},
#            "done_reason": "stop", "prompt_eval_count": 18, "eval_count": 70}
# glm-5.3-flash:cloud is a thinking model: "content" is the visible answer,
# "thinking" (when present) is the reasoning trace. Token fields may be absent.

import sys
import time

import requests

from config.settings import OLLAMA_API_KEY, OLLAMA_CLOUD_HOST, OLLAMA_CLOUD_MODEL

ENDPOINT_PATH = "/api/chat"
DEFAULT_TIMEOUT_S = 120


class LlmError(Exception):
    """Typed error with a user-friendly message; never a raw traceback."""


def call_llm(prompt: str, *, host: str | None = None, model: str | None = None,
             api_key: str | None = None, timeout_s: int | None = None) -> dict:
    """Call the Ollama chat API. Defaults come from settings (cloud config);
    MaintAI passes LLM_BASE_URL/LLM_MODEL/LLM_TIMEOUT_SECONDS explicitly."""
    host = host or OLLAMA_CLOUD_HOST
    model = model or OLLAMA_CLOUD_MODEL
    api_key = api_key if api_key is not None else OLLAMA_API_KEY
    timeout_s = timeout_s or DEFAULT_TIMEOUT_S
    url = f"{host}{ENDPOINT_PATH}"
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    start = time.perf_counter()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout_s)
    except requests.exceptions.Timeout:
        raise LlmError(
            f"Ollama Cloud timed out after {timeout_s}s. Try again or pick a smaller model."
        )
    except requests.exceptions.ConnectionError:
        raise LlmError(
            f"Cannot reach the LLM at {host}. Check your network connection."
        )
    except requests.exceptions.RequestException:  # any other transport error
        raise LlmError(
            f"LLM connection failed ({host}). Check the base-URL env setting and "
            "your network, then retry."
        )

    if resp.status_code == 401 or resp.status_code == 403:
        raise LlmError("Ollama Cloud authentication failed. Check OLLAMA_API_KEY in .env.")
    if resp.status_code == 404:
        raise LlmError(
            f"Model '{model}' unavailable. Set a valid OLLAMA_CLOUD_MODEL in .env."
        )
    if resp.status_code != 200:
        raise LlmError(  # ponytail: first 200 chars - body never leaks the key
            f"LLM request failed (HTTP {resp.status_code}). {resp.text[:200]}"
        )

    try:
        data = resp.json()
    except ValueError:
        raise LlmError("The LLM service returned an invalid (non-JSON) response.")

    message = data.get("message") or {}
    content = message.get("content")
    if not content:
        raise LlmError("The LLM service returned an empty response.")

    result = {
        "model": data.get("model", model),
        "text": content,
        "elapsed_s": round(time.perf_counter() - start, 2),
        # thinking trace only when the model provides one (never fabricated)
        "thinking": message.get("thinking"),
        # token fields only when supplied — never fabricated
        "prompt_tokens": data.get("prompt_eval_count"),
        "eval_tokens": data.get("eval_count"),
        "done_reason": data.get("done_reason"),
    }
    return result


if __name__ == "__main__":
    # Self-test: prompt from argv or a safe default.
    arg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Say OK in one word."

    out = call_llm(arg)
    print(f"Model:       {out['model']}")
    print(f"Elapsed:     {out['elapsed_s']} sec")
    print(f"Tokens:      prompt={out['prompt_tokens']} eval={out['eval_tokens']}")
    print(f"Text:        {out['text']}")
    if out["thinking"]:
        print(f"Thinking:    {out['thinking'][:200]}...")