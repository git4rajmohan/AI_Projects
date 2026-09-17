"""
Demo 3: RAG Query Pipeline
Run a question through the full RAG pipeline:
retrieve → build prompt → generate answer with citations.

Usage:
    python demo/03_query.py "How does FastMCP register a tool?"
    python demo/03_query.py "What is the difference between Stdio and Streamable HTTP?"
    python demo/03_query.py "What is the rate limit on the Stripe API?"
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.graph import run_query


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python demo/03_query.py "<your question>"')
        sys.exit(1)
    main_with_query(sys.argv[1])


def main_with_query(query: str) -> None:
    """Run the full RAG pipeline for a given query and print formatted output."""
    print(f"\nQuery: {query}\n")

    answer = run_query(query)

    width = 67
    print(f"{'─' * width}")
    print("ANSWER")
    print(f"{'─' * width}")
    print(answer.text)

    print(f"\n{'─' * width}")
    print("CITATIONS")
    print(f"{'─' * width}")
    if answer.citations:
        for citation in answer.citations:
            print(f"  {citation}")
    else:
        print("  No citations found.")

    print(f"\n{'─' * width}")
    print("CHUNKS USED")
    print(f"{'─' * width}")
    print(f"  {answer.chunks_used} chunks retrieved")
    print(f"{'─' * width}\n")


if __name__ == "__main__":
    main()
