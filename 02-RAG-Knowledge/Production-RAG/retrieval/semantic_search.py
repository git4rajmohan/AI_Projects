from dataclasses import dataclass
from typing import List

import chromadb

from vectorstore.embedder import EmbeddingModel


@dataclass
class RetrievedChunk:
    content: str
    metadata: dict
    score: float   # distance score from ChromaDB (lower = more similar)
    rank: int      # 1-indexed position in results


def search(
    query: str,
    collection: chromadb.Collection,
    model: EmbeddingModel,
    top_k: int,
) -> List[RetrievedChunk]:
    """
    Embed the query, query the ChromaDB collection, return top_k results
    as RetrievedChunk objects ranked by similarity score.
    """
    query_embedding = model.encode([query])[0].tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks: List[RetrievedChunk] = []
    for rank, (doc, meta, dist) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        chunks.append(RetrievedChunk(
            content=doc,
            metadata=meta,
            score=dist,
            rank=rank + 1,
        ))

    return chunks
