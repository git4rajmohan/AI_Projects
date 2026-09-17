"""RRF rank diagnostic at various top_k for the g-001 query family."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from app.retrieval.hybrid_retriever import HybridRetriever

QUERIES = [
    "How many annual leave days do employees receive in their first two years?",
    "How many annual leave days do employees receive?",
]
TARGET_MARKERS = ("15 days", "0-2 years")


def main() -> None:
    retriever = HybridRetriever()
    for query in QUERIES:
        evidence = retriever.retrieve(query, top_k=10)
        print("Q:", query)
        for i, hit in enumerate(evidence.fused_hits, 1):
            mark = " <<< TARGET" if any(m in hit.text for m in TARGET_MARKERS) else ""
            text = " ".join(hit.text.split())[:50]
            print(f"  {i:2d} rrf={hit.rrf_score:.4f} {hit.document[:36]:36s} | {text}{mark}")
        print()


if __name__ == "__main__":
    main()