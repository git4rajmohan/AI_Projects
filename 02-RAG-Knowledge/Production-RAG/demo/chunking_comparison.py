"""
Demo 1: Chunking Strategy Comparison
Shows why character splitting fails on technical documentation
and how semantic chunking preserves meaning boundaries.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chunking.comparison import compare_strategies, ComparisonResult


def main() -> None:
    result = compare_strategies("docs/MCP_Documentation.md")
    print_comparison(result)


def print_comparison(result: ComparisonResult) -> None:
    width = 67

    # Header box
    print(f"┌{'─' * width}┐")
    print(f"│{'CHUNKING STRATEGY COMPARISON':^{width}}│")
    print(f"│{f'Document: {result.doc_title}':^{width}}│")
    print(f"└{'─' * width}┘")

    # Statistics table
    print("\nSTATISTICS")
    print(f"{'─' * width}")
    print(f"{'':26}{'CHARACTER':<22}{'SEMANTIC'}")
    print(f"{'':26}{'SPLITTER (bad)':<22}{'SPLITTER (good)'}")
    print(f"{'─' * width}")

    cs = result.char_stats
    ss = result.semantic_stats

    print(f"{'Total chunks':<26}{str(cs['total_chunks']):<22}{ss['total_chunks']}")
    print(f"{'Avg words/chunk':<26}{str(cs['avg_words']):<22}{ss['avg_words']}")
    print(f"{'Broken code blocks':<26}{str(cs['broken_code_blocks']):<22}{ss['broken_code_blocks']}")
    print(f"{'Broken tables':<26}{str(cs['broken_tables']):<22}{ss['broken_tables']}")
    print(f"{'─' * width}")

    # ── CHARACTER SPLITTER: 3 problem examples ──────────────────────
    print(f"\nCHARACTER SPLITTER — 3 Problem Examples")
    print(f"{'─' * width}")

    broken_code = [
        c for c in result.char_chunks
        if c.has_code_block and c.content.count("```") % 2 != 0
    ]
    broken_table = [
        c for c in result.char_chunks
        if c.has_table
    ]

    # Collect up to 3 interesting problem chunks without repeating
    shown: set = set()
    problem_chunks = []
    for c in broken_code:
        if c.metadata["chunk_index"] not in shown and len(problem_chunks) < 2:
            problem_chunks.append(c)
            shown.add(c.metadata["chunk_index"])
    for c in broken_table:
        if c.metadata["chunk_index"] not in shown and len(problem_chunks) < 3:
            problem_chunks.append(c)
            shown.add(c.metadata["chunk_index"])
    # Fill remaining slots with arbitrary chunks that weren't already picked
    for c in result.char_chunks:
        if c.metadata["chunk_index"] not in shown and len(problem_chunks) < 3:
            problem_chunks.append(c)
            shown.add(c.metadata["chunk_index"])

    for chunk in problem_chunks:
        flags = []
        if chunk.has_code_block and chunk.content.count("```") % 2 != 0:
            flags.append("BROKEN CODE BLOCK")
        if chunk.has_table:
            flags.append("HAS TABLE")
        flag_str = " | " + " | ".join(flags) if flags else ""
        label = (
            f"Chunk {chunk.metadata['chunk_index']} | "
            f"{len(chunk.content)} chars | "
            f"has_code_block={chunk.has_code_block}"
            f"{flag_str}"
        )
        print(f"[{label}]")
        preview = chunk.content[:250]
        print(preview + ("..." if len(chunk.content) > 250 else ""))
        print()

    # ── SEMANTIC SPLITTER: 3 clean examples ─────────────────────────
    print(f"\nSEMANTIC SPLITTER — 3 Clean Examples")
    print(f"{'─' * width}")

    for chunk in result.semantic_chunks[:3]:
        section = chunk.metadata.get("section_title", "Unknown")
        subsection = chunk.metadata.get("subsection_title", "")
        label_section = subsection if subsection else section
        code_note = "code intact" if chunk.has_code_block else "no code"
        table_note = " | table intact" if chunk.has_table else ""
        print(f"[Section: \"{label_section}\" | {chunk.word_count} words | {code_note}{table_note}]")
        preview = chunk.content[:200]
        print(preview + ("..." if len(chunk.content) > 200 else ""))
        print()

    print(f"{'─' * width}")


if __name__ == "__main__":
    main()
