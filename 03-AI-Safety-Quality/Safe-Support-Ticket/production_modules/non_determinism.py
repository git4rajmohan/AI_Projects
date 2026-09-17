"""
Controlling non-determinism in LLM outputs via temperature and seed.

# PRODUCTION NOTE: Use temperature=0 + seed for classification/routing tasks
# where consistency is critical. Reserve higher temperatures (0.3-0.7) for
# generative tasks like drafting responses or summaries where creative variation
# improves quality. Document your temperature choice in the prompt version registry.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from schema import TicketClassification

load_dotenv()

_DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss:120b")

# Ollama Cloud (OpenAI-compatible endpoint) — same wiring as structured_output.
_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
_OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "not-set")


def build_deterministic_llm(model: str = _DEFAULT_MODEL, seed: int = 42) -> ChatOpenAI:
    """
    temperature=0  → greedy decoding, most probable token always chosen.
    seed           → ensures identical sampling sequence across calls (where supported).
    Together they give near-identical outputs for the same input.
    """
    return ChatOpenAI(
        model=model,
        temperature=0,
        seed=seed,
        base_url=_OLLAMA_BASE_URL,
        api_key=_OLLAMA_API_KEY,
    )


def build_creative_llm(model: str = _DEFAULT_MODEL, temperature: float = 0.7) -> ChatOpenAI:
    """
    Higher temperature for tasks where variation is desirable, e.g.
    generating empathetic reply drafts or brainstorming resolutions.
    """
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url=_OLLAMA_BASE_URL,
        api_key=_OLLAMA_API_KEY,
    )


def classify_ticket(ticket_text: str, llm: ChatOpenAI) -> TicketClassification:
    structured_llm = llm.with_structured_output(TicketClassification)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert customer support ticket classifier."),
        ("human", "Classify this support ticket:\n\n{ticket_text}"),
    ])
    chain = prompt | structured_llm
    return chain.invoke({"ticket_text": ticket_text})


def run_consistency_test(ticket_text: str, runs: int = 5) -> dict:
    """
    Run the same ticket N times with temperature=0 and assert all categories match.
    Returns a summary dict.
    """
    llm = build_deterministic_llm()
    results = [classify_ticket(ticket_text, llm) for _ in range(runs)]
    categories = [r.issue_category for r in results]
    all_match = len(set(categories)) == 1
    return {
        "all_match": all_match,
        "category": categories[0] if all_match else "MISMATCH",
        "all_categories": [c.value for c in categories],
    }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ticket = "My package was supposed to arrive 5 days ago. Where is it?"

    print("Running consistency test (5 runs, temperature=0, seed=42)...")
    summary = run_consistency_test(ticket)
    print(f"All outputs match: {summary['all_match']}")
    print(f"Category        : {summary['category']}")
    print(f"All categories  : {summary['all_categories']}")

    assert summary["all_match"], "Determinism test failed — outputs are not consistent!"
    print("\nDeterminism test PASSED.")
