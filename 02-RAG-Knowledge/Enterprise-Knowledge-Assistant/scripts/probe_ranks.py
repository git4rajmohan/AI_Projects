"""Rank diagnostic: where does the PTO accrual chunk rank per retrieval leg?

Data-gathering for the item-9 (re-ranker) deferral decision — measures real
ranks of the target chunk for the g-001 query across both chunk legs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows console (cp932/cp1252) crashes on chunk glyphs — same gotcha as the
# pytest conftest; force UTF-8 with replacement for the whole process.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.vector_retriever import VectorRetriever

QUERIES = {
    "g-001 phrasing": "How many annual leave days do employees receive in their first two years?",
    "direct phrasing": "How many annual leave days do employees receive?",
    "table phrasing": "PTO accrual schedule tenure annual PTO days",
}
TARGET_MARKERS = ("15 days", "0-2 years", "5.0 hours")


def _mark(text: str) -> str:
    return "  <<< TARGET" if any(m in text for m in TARGET_MARKERS) else ""


def main() -> None:
    bm25 = BM25Retriever()
    bm25.build()
    for label, query in QUERIES.items():
        vec = VectorRetriever().retrieve(query, top_k=15)
        kw = bm25.retrieve(query, top_k=15)
        print("=" * 100)
        print(label, "->", query)
        print("--- vector top15 ---")
        for i, h in enumerate(vec, 1):
            print(f"{i:2d} {h.score:.4f} {h.document[:40]:40s} | {' '.join(h.text.split())[:55]}{_mark(h.text)}")
        print("--- bm25 top15 ---")
        for i, h in enumerate(bm25.retrieve(query, top_k=15), 1):
            print(f"{i:2d} {h.score:8.3f} {h.document[:40]:40s} | {' '.join(h.text.split())[:55]}{_mark(h.text)}")


if __name__ == "__main__":
    main()