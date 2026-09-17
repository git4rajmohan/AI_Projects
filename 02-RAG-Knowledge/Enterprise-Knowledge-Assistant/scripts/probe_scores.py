"""Score calibration probe — measures REAL similarity-score behavior of the
Cognee `DocumentChunk_text` collection so the enforcement-gate threshold
(item 10) is set from data, not guesses.

Prints, for a set of known-question / unknown-question queries:
  * top-5 cosine similarity scores for each query
  * per-query max score distribution

Run:  .venv\\Scripts\\python.exe scripts\\probe_scores.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings
from app.retrieval.vector_retriever import VectorRetriever

KNOWN_QUERIES = [
    "How many annual leave days do employees receive?",
    "Which policy governs remote work?",
    "What is the password policy requirement?",
    "How do employees report a security incident?",
    "What benefits does the company offer?",
    "How is equipment provided for remote workers?",
]
UNKNOWN_QUERIES = [
    "What is the company's private jet travel policy?",
    "Who won the 1998 FIFA World Cup final?",
    "What is the recipe for chocolate chip cookies?",
    "How much does a Tesla Model 3 cost?",
    "What are the opening hours of the Louvre museum?",
]


def main() -> None:
    settings = get_settings()
    retriever = VectorRetriever(settings)
    print("=" * 78)
    print("KNOWN QUESTIONS (corpus contains answers — scores should be high)")
    print("=" * 78)
    known_maxes = []
    for query in KNOWN_QUERIES:
        hits = retriever.retrieve(query, top_k=5)
        scores = [round(h.score, 4) for h in hits]
        known_maxes.append(scores[0] if scores else 0.0)
        print(f"\nQ: {query}")
        print(f"   scores: {scores}")
        if hits:
            print(f"   top text: {hits[0].text[:100]!r}")
    print("\n" + "=" * 78)
    print("UNKNOWN QUESTIONS (corpus cannot answer — scores should be lower)")
    print("=" * 78)
    unknown_maxes = []
    for query in UNKNOWN_QUERIES:
        hits = retriever.retrieve(query, top_k=5)
        scores = [round(h.score, 4) for h in hits]
        unknown_maxes.append(scores[0] if scores else 0.0)
        print(f"\nQ: {query}")
        print(f"   scores: {scores}")
        if hits:
            print(f"   top text: {hits[0].text[:100]!r}")
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"known   max scores: {sorted(known_maxes)}")
    print(f"unknown max scores: {sorted(unknown_maxes)}")
    if known_maxes and unknown_maxes:
        print(f"min known max  = {min(known_maxes):.4f}")
        print(f"max unknown max = {max(unknown_maxes):.4f}")
        print(f"gap            = {min(known_maxes) - max(unknown_maxes):.4f}")


if __name__ == "__main__":
    main()