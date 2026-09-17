"""
Structured output from LLM — the single place in the codebase that makes
classification LLM calls. Both approaches accept a system_prompt argument
so the caller (graph node or retry wrapper) controls prompt content without
touching LLM wiring.

# PRODUCTION NOTE: In a real system, prefer function-calling (approach 1) as
# it is more reliable and model-native. Fall back to JSON mode only for models
# that don't support tool/function calling. Always validate the output with
# Pydantic regardless of which approach you use.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError
from schema import TicketClassification

load_dotenv()

_DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss:120b")

# Ollama Cloud serves an OpenAI-compatible /v1 endpoint, so ChatOpenAI works
# as the client with just a base-url and API key override.
_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
_OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "not-set")

DEFAULT_SYSTEM_PROMPT = "You are an expert customer support ticket classifier."

# Used by fallback_retry on retry attempts — simpler, more conservative
SIMPLE_SYSTEM_PROMPT = (
    "You are a support ticket classifier. Classify into one of: "
    "order_issue, payment_issue, delivery_issue, product_issue, account_issue, refund_request, other. "
    "Keep confidence low and set requires_human_review=True if unsure."
)


def _extract_json(text: str) -> dict:
    """Parse JSON from a model response, tolerating markdown code fences.

    Some models wrap JSON output in ```json ... ``` blocks; strip the fences
    before parsing so the pipeline does not crash on cosmetic formatting.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"```\s*$", "", stripped)
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# Approach 1: Function-calling (recommended)
# Use when: the model supports tool/function calling (GPT-4, GPT-3.5-turbo-1106+)
# Pros: Model is explicitly told the schema; more reliable JSON adherence.
# Cons: Slightly higher token overhead for the schema definition.
# ---------------------------------------------------------------------------

def classify_with_function_calling(
    ticket_text: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    model: str = _DEFAULT_MODEL,
    seed: int = 42,
) -> TicketClassification:
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        seed=seed,
        base_url=_OLLAMA_BASE_URL,
        api_key=_OLLAMA_API_KEY,
    )
    structured_llm = llm.with_structured_output(TicketClassification)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Classify this support ticket:\n\n{ticket_text}"),
    ])

    chain = prompt | structured_llm
    return chain.invoke({"ticket_text": ticket_text})


# ---------------------------------------------------------------------------
# Approach 2: JSON mode
# Use when: you need the model to freely structure its output as JSON but
# don't want to pin to a specific schema via tool calling, or when using
# older models that lack function-calling support.
# Pros: Simpler setup; works across more models.
# Cons: Must parse + validate manually; model may deviate from expected fields.
# ---------------------------------------------------------------------------

def classify_with_json_mode(
    ticket_text: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    model: str = _DEFAULT_MODEL,
    seed: int = 42,
) -> TicketClassification:
    schema_json = json.dumps(TicketClassification.model_json_schema(), indent=2)
    # Escape braces so LangChain's template engine doesn't treat them as
    # variable placeholders (e.g. {"type": "string"} → {{"type": "string"}})
    schema_escaped = schema_json.replace("{", "{{").replace("}", "}}")
    full_system = f"{system_prompt}\n\nReturn ONLY valid JSON matching this schema:\n{schema_escaped}"

    llm = ChatOpenAI(
        model=model,
        temperature=0,
        seed=seed,
        base_url=_OLLAMA_BASE_URL,
        api_key=_OLLAMA_API_KEY,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", full_system),
        ("human", "Classify this support ticket:\n\n{ticket_text}"),
    ])

    chain = prompt | llm
    response = chain.invoke({"ticket_text": ticket_text})
    raw = _extract_json(response.content)
    print(json.dumps(raw, indent=4))
    return TicketClassification.model_validate(raw)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ticket = "I was charged twice for order #9981. Please refund immediately!"

    print("=== Approach 1: Function-calling ===")
    result1 = classify_with_function_calling(ticket)
    print(result1.model_dump_json(indent=2))

    print("\n=== Approach 2: JSON mode ===")
    result2 = classify_with_json_mode(ticket)
    print(result2.model_dump_json(indent=2))
