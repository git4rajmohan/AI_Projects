from typing import List

import chromadb
from rank_bm25 import BM25Okapi

from retrieval.semantic_search import RetrievedChunk
from vectorstore.embedder import EmbeddingModel


def _stage_entry(meta: dict, text: str, *, score: float, score_key: str) -> dict:
    """UI-friendly summary row for one candidate in a ranking stage."""
    return {
        "doc_id": f"{meta.get('doc_title', '?')}_{meta.get('chunk_index', '?')}",
        "doc_title": meta.get("doc_title", "?"),
        "section_title": meta.get("section_title", meta.get("strategy", "?")),
        "score": round(score, 4),
        "score_key": score_key,
        "preview": text[:80].replace("\n", " "),
    }


def search_with_trace(
    query: str,
    collection: chromadb.Collection,
    model: EmbeddingModel,
    top_k: int,
    rrf_k: int = 60,
    overfetch_factor: int = 2,
) -> dict:
    """
    Run BM25 keyword search over all chunk texts in the collection.
    Run vector similarity search via the collection.
    Merge both ranked lists using Reciprocal Rank Fusion (RRF):
        rrf_score = 1/(rank_bm25 + k) + 1/(rank_vector + k)
    Return top_k results sorted by RRF score descending, plus the full
    per-stage ranking trace for UI inspection:
        { final: List[RetrievedChunk],
          trace: { bm25: [...], vector: [...], fused: [...] } }
    Each trace stage is a list of {doc_id, doc_title, section_title, score,
    score_key, preview} ordered best-first. The fused stage also carries
    the per-list rank contributions (bm25_rank / vector_rank).
    """
    # Fetch all documents to build the BM25 corpus
    all_docs = collection.get(include=["documents", "metadatas"])
    documents: List[str] = all_docs["documents"]
    metadatas: List[dict] = all_docs["metadatas"]
    ids: List[str] = all_docs["ids"]

    if not documents:
        return {"final": [], "trace": {"bm25": [], "vector": [], "fused": []}}

    # BM25 keyword search
    tokenized_corpus = [doc.lower().split() for doc in documents]
    bm25 = BM25Okapi(tokenized_corpus)
    bm25_scores = bm25.get_scores(query.lower().split())
    bm25_ranked = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)

    bm25_trace = [
        _stage_entry(metadatas[i], documents[i], score=bm25_scores[i], score_key="bm25")
        for i in bm25_ranked[:top_k]
    ]

    # Vector similarity search
    query_embedding = model.encode([query])[0].tolist()
    n_results = min(top_k * overfetch_factor, len(documents))
    vector_results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    vector_ids: List[str] = vector_results["ids"][0]
    vector_distances: List[float] = vector_results["distances"][0]

    # Build lookup maps
    id_to_index = {doc_id: i for i, doc_id in enumerate(ids)}

    vector_trace = []
    for vid, dist in zip(vector_ids, vector_distances):
        idx = id_to_index.get(vid, -1)
        if idx < 0:
            continue
        vector_trace.append(
            _stage_entry(metadatas[idx], documents[idx], score=dist, score_key="distance")
        )

    vector_rank_map = {vid: rank for rank, vid in enumerate(vector_ids)}

    # Reciprocal Rank Fusion
    rrf_scores: dict[str, float] = {}
    bm25_rank_of: dict[str, int] = {}
    vector_rank_of: dict[str, int] = {}

    for rank, corpus_idx in enumerate(bm25_ranked):
        doc_id = ids[corpus_idx]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (rank + rrf_k)
        bm25_rank_of[doc_id] = rank

    for vid, _dist in zip(vector_ids, vector_distances):
        rank = vector_rank_map[vid]
        rrf_scores[vid] = rrf_scores.get(vid, 0.0) + 1.0 / (rank + rrf_k)
        vector_rank_of[vid] = rank

    # Return top_k by RRF score
    sorted_ids = sorted(rrf_scores, key=lambda d: rrf_scores[d], reverse=True)[:top_k]

    fused_trace = []
    chunks: List[RetrievedChunk] = []
    for rank, doc_id in enumerate(sorted_ids):
        idx = id_to_index[doc_id]
        meta = metadatas[idx]
        entry = _stage_entry(meta, documents[idx], score=rrf_scores[doc_id], score_key="rrf")
        entry["bm25_rank"] = bm25_rank_of.get(doc_id)
        entry["vector_rank"] = vector_rank_of.get(doc_id)
        fused_trace.append(entry)
        chunks.append(RetrievedChunk(
            content=documents[idx],
            metadata=meta,
            score=rrf_scores[doc_id],
            rank=rank + 1,
        ))

    return {
        "final": chunks,
        "trace": {"bm25": bm25_trace, "vector": vector_trace, "fused": fused_trace},
    }


def search(
    query: str,
    collection: chromadb.Collection,
    model: EmbeddingModel,
    top_k: int,
) -> List[RetrievedChunk]:
    """
    Run BM25 keyword search over all chunk texts in the collection.
    Run vector similarity search via the collection.
    Merge both ranked lists using Reciprocal Rank Fusion (RRF):
        rrf_score = 1/(rank_bm25 + 60) + 1/(rank_vector + 60)
    Return top_k results sorted by RRF score descending.
    """
    return search_with_trace(query, collection, model, top_k)["final"]
