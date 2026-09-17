import re
from typing import List
from chunking.character_splitter import Chunk


def split_by_headers(text: str, doc_title: str, max_words: int) -> List[Chunk]:
    """
    Split Markdown text at ## header boundaries (semantic chunking).
    If any resulting section exceeds max_words, split it further at ### headers
    (hybrid chunking). This preserves code blocks and tables intact within
    their natural section boundary.
    """
    h2_parts = re.split(r'\n(?=## )', text)
    chunks: List[Chunk] = []
    chunk_index = 0

    for part in h2_parts:
        if not part.strip():
            continue

        # Extract the H2 section title from the first line
        lines = part.split('\n', 1)
        first_line = lines[0].strip()
        section_title = first_line.lstrip('#').strip() if first_line.startswith('#') else first_line

        word_count = len(part.split())

        if word_count > max_words:
            # Hybrid chunking: split oversized H2 sections at H3 boundaries
            h3_parts = re.split(r'\n(?=### )', part)

            for h3_part in h3_parts:
                if not h3_part.strip():
                    continue

                h3_lines = h3_part.split('\n', 1)
                h3_first = h3_lines[0].strip()
                subsection_title: str | None = h3_first.lstrip('#').strip() if h3_first.startswith('#') else None

                content = h3_part.strip()
                wc = len(content.split())

                chunks.append(Chunk(
                    content=content,
                    metadata={
                        "doc_title": doc_title,
                        "section_title": section_title,
                        "subsection_title": subsection_title if subsection_title else "",
                        "chunk_index": chunk_index,
                        "strategy": "semantic",
                        "word_count": wc,
                    },
                    word_count=wc,
                    has_code_block="```" in content,
                    has_table="|---|" in content,
                ))
                chunk_index += 1
        else:
            content = part.strip()
            chunks.append(Chunk(
                content=content,
                metadata={
                    "doc_title": doc_title,
                    "section_title": section_title,
                    "subsection_title": "",
                    "chunk_index": chunk_index,
                    "strategy": "semantic",
                    "word_count": word_count,
                },
                word_count=word_count,
                has_code_block="```" in content,
                has_table="|---|" in content,
            ))
            chunk_index += 1

    return chunks
