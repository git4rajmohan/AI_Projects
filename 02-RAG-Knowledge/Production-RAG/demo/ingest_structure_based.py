"""
Demo 2: Document Ingestion Pipeline
Loads documents, applies semantic chunking, embeds chunks,
and persists them to ChromaDB on disk.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    CHROMA_PATH,
    COLLECTION_NAME,
    DOCS_PATH,
    EMBED_MODEL,
    SEMANTIC_MAX_WORDS,
)
from chunking.semantic_splitter import split_by_headers
from vectorstore.embedder import embed_chunks, load_embedding_model
from vectorstore.store import get_or_create_collection, upsert_chunks


def main() -> None:
    # 1. Discover all .md files in DOCS_PATH
    md_files = sorted([
        os.path.join(DOCS_PATH, f)
        for f in os.listdir(DOCS_PATH)
        if f.endswith(".md")
    ])
    print(f"Found {len(md_files)} document(s): {[os.path.basename(f) for f in md_files]}\n")

    # 2. For each document: read text, call split_by_headers, collect chunks
    all_chunks = []
    for doc_path in md_files:
        doc_title = os.path.basename(doc_path)
        with open(doc_path, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = split_by_headers(text, doc_title, SEMANTIC_MAX_WORDS)
        print(f"  {doc_title}: {len(chunks)} semantic chunks")
        all_chunks.extend(chunks)

    print(f"\nTotal chunks to embed: {len(all_chunks)}")

    # 3. Load embedding model once
    model = load_embedding_model(EMBED_MODEL)

    # 4. Embed all chunks in one batch
    embeddings = embed_chunks(all_chunks, model)

    # 5. Get or create ChromaDB collection
    collection = get_or_create_collection(CHROMA_PATH, COLLECTION_NAME)

    # 6. Upsert all chunks with their embeddings
    upsert_chunks(collection, all_chunks, embeddings)

    # 7. Print final summary
    print(f"\nIngestion complete:")
    print(f"  Documents processed : {len(md_files)}")
    print(f"  Total chunks stored : {len(all_chunks)}")
    print(f"  ChromaDB path       : ./{CHROMA_PATH}")


if __name__ == "__main__":
    main()
