import os
from dataclasses import dataclass
from typing import List

from chunking.character_splitter import Chunk, split_by_characters
from chunking.semantic_splitter import split_by_headers
from config.settings import CHAR_CHUNK_SIZE, CHAR_CHUNK_OVERLAP, SEMANTIC_MAX_WORDS


@dataclass
class ComparisonResult:
    doc_title: str
    char_chunks: List[Chunk]
    semantic_chunks: List[Chunk]
    char_stats: dict     # total_chunks, avg_words, broken_code_blocks, broken_tables
    semantic_stats: dict # total_chunks, avg_words, broken_code_blocks, broken_tables


def _has_complete_table_row(content: str) -> bool:
    """Return True if content has at least two table lines (a data row plus a separator)."""
    lines = content.split('\n')
    table_lines = [line for line in lines if '|' in line]
    return len(table_lines) >= 2


def _compute_stats(chunks: List[Chunk]) -> dict:
    """Compute summary statistics for a list of chunks."""
    total = len(chunks)
    avg_words = sum(c.word_count for c in chunks) / total if total > 0 else 0.0
    broken_code_blocks = sum(
        1 for c in chunks
        if c.has_code_block and c.content.count("```") % 2 != 0
    )
    broken_tables = sum(
        1 for c in chunks
        if c.has_table and not _has_complete_table_row(c.content)
    )
    return {
        "total_chunks": total,
        "avg_words": round(avg_words, 1),
        "broken_code_blocks": broken_code_blocks,
        "broken_tables": broken_tables,
    }


def compare_strategies(doc_path: str) -> ComparisonResult:
    """
    Load a Markdown document, run both chunking strategies on it,
    compute statistics for each, and return a ComparisonResult.
    Called directly by demo/01_chunking_comparison.py.
    """
    doc_title = os.path.basename(doc_path)

    with open(doc_path, "r", encoding="utf-8") as f:
        text = f.read()

    char_chunks = split_by_characters(text, doc_title, CHAR_CHUNK_SIZE, CHAR_CHUNK_OVERLAP)
    semantic_chunks = split_by_headers(text, doc_title, SEMANTIC_MAX_WORDS)

    return ComparisonResult(
        doc_title=doc_title,
        char_chunks=char_chunks,
        semantic_chunks=semantic_chunks,
        char_stats=_compute_stats(char_chunks),
        semantic_stats=_compute_stats(semantic_chunks),
    )
