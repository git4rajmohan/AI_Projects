"""Phase 7 manual verification: ask one question end-to-end and print REAL output.

Run with services up:
    .\\.venv\\Scripts\\python.exe -X utf8 scripts\\ask_question.py "How many annual leave days do employees receive?"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings
from app.retrieval.llamaindex_engine import LlamaIndexEngine


def main() -> None:
    question = " ".join(sys.argv[1:]) or "How many annual leave days do employees receive?"
    settings = get_settings()
    print(f"provider={settings.provider} llm={settings.llm_model} embed={settings.embed_model}")
    engine = LlamaIndexEngine()
    result = engine.answer(question)
    print("\n=== ANSWER ===")
    print(result.answer)
    print("\n=== SOURCES (from retrieved evidence) ===")
    for i, source in enumerate(result.sources, 1):
        print(f" {i}. {source}")
    print("\n=== VECTOR HITS ===")
    for i, hit in enumerate(result.vector_hits, 1):
        print(f" [{i}] score={hit.score:.4f} doc={hit.document}")
        print(f"     {hit.text[:120].replace(chr(10), ' ')}...")


if __name__ == "__main__":
    main()