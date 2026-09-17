"""
Embedding-based semantic chunking.

Splits text into sentences, embeds each sentence locally, and cuts chunks at
"semantic breakpoints": consecutive sentence pairs whose cosine similarity
drops below a (buffered) percentile of all pair similarities. This is the
technique enterprises use for semantic chunking — no chat LLM involved.
"""
from typing import List

import numpy as np

from chunking.character_splitter import Chunk
from vectorstore.embedder import EmbeddingModel


def _split_sentences(text: str) -> List[str]:
    """
    Split text into sentences on [.!?] followed by whitespace + capital,
    keeping Markdown headers (## ...) as their own sentences so section
    starts are eligible breakpoint candidates. Falls back to newline
    splitting when the text has almost no sentence punctuation.
    """
    import re

    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z#*|>-])', text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        # No sentence punctuation (e.g. code-heavy text): split on lines.
        parts = [line for line in text.splitlines() if line.strip()]
    return parts


def split_by_embeddings(
    text: str,
    doc_title: str,
    model: EmbeddingModel,
    buffer_size: int = 1,
    percentile_threshold: int = 95,
    min_chunk_size: int = 100,
) -> List[Chunk]:
    """
    1. Split into sentences.
    2. Embed every sentence (local embedding model, no LLM).
    3. Compute cosine similarity of consecutive sentence pairs.
    4. A breakpoint goes where similarity < (percentile of similarities
       minus buffer-size lookahead): the topic is shifting.
    5. Pack sentences between breakpoints into chunks, never below
       min_chunk_size chars (small fragments merge into the next chunk).

    Returns Chunk objects with the same metadata schema as the other
    splitters (strategy="semantic-embedding", section_title = first
    sentence's first words for citation display).
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []
    if len(sentences) == 1:
        return [_make_chunk(sentences[0], doc_title, 0, model)]

    vectors = model.encode(sentences)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vectors / norms
    # cosine similarity of each consecutive pair
    pair_sims = np.sum(unit[:-1] * unit[1:], axis=1)

    cutoff = float(np.percentile(pair_sims, percentile_threshold))
    breakpoints = _find_breakpoints(pair_sims, cutoff, buffer_size)

    # Pack sentences into chunks at the breakpoints
    chunks: List[Chunk] = []
    buf: List[str] = []
    chunk_index = 0
    for i, sentence in enumerate(sentences):
        buf.append(sentence)
        at_break = i in breakpoints
        at_end = i == len(sentences) - 1
        if at_break or at_end:
            content = " ".join(buf).strip()
            if len(content) < min_chunk_size and not at_end and chunks:
                # too small: merge into the previous chunk
                prev = chunks[-1]
                prev.content += " " + content
                prev.word_count += len(content.split())
                prev.metadata["section_title"] = prev.metadata["section_title"]  # unchanged
                buf = []
                continue
            chunks.append(_make_chunk(content, doc_title, chunk_index, model))
            chunk_index += 1
            buf = []
    if buf:
        content = " ".join(buf).strip()
        if chunks:
            chunks[-1].content += " " + content
            chunks[-1].word_count += len(content.split())
        else:
            chunks.append(_make_chunk(content, doc_title, chunk_index, model))
    return chunks


def _find_breakpoints(pair_sims: np.ndarray, cutoff: float, buffer_size: int) -> set:
    """Breakpoint after sentence i when pair_sims[i] < cutoff. buffer_size
    (Greg Kamradt style) looks backward: within every buffer_size+1 window,
    only the single strongest drop becomes a breakpoint, avoiding clusters
    of tiny chunks at near-identical similarity dips."""
    breakpoints: set = set()
    i = 0
    while i < len(pair_sims):
        if pair_sims[i] < cutoff:
            start = max(0, i - buffer_size)
            end = min(i + 1, len(pair_sims))
            window = pair_sims[start:end]
            argmin = int(np.argmin(window))
            breakpoints.add(start + argmin)
            i = end + buffer_size
        else:
            i += 1
    return breakpoints


def _make_chunk(content: str, doc_title: str, chunk_index: int, model: EmbeddingModel) -> Chunk:
    # section_title: short label from the content head, used for citations
    first_line = content.splitlines()[0] if content else ""
    section_title = first_line.strip().lstrip("#").strip()[:60] or "Semantically grouped"
    return Chunk(
        content=content,
        metadata={
            "doc_title": doc_title,
            "section_title": section_title,
            "subsection_title": "",
            "chunk_index": chunk_index,
            "strategy": "semantic-embedding",
            "word_count": len(content.split()),
        },
        word_count=len(content.split()),
        has_code_block="```" in content,
        has_table="|---|" in content,
    )