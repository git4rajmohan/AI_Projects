from dataclasses import dataclass
from typing import List


@dataclass
class Chunk:
    content: str
    metadata: dict        # keys: doc_title, chunk_index, strategy, char_start, char_end
    word_count: int
    has_code_block: bool  # True if content contains ```
    has_table: bool       # True if content contains |---|


def split_by_characters(text: str, doc_title: str, chunk_size: int, overlap: int) -> List[Chunk]:
    """
    Split text at fixed character intervals with overlap.
    Does not respect sentence, paragraph, or section boundaries.
    Produces the 'bad' chunks used in the comparison demo.
    """
    chunks = []
    step = chunk_size - overlap
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        content = text[start:end]

        chunks.append(Chunk(
            content=content,
            metadata={
                "doc_title": doc_title,
                "chunk_index": chunk_index,
                "strategy": "character",
                "char_start": start,
                "char_end": end,
            },
            word_count=len(content.split()),
            has_code_block="```" in content,
            has_table="|---|" in content,
        ))

        start += step
        chunk_index += 1

    return chunks
