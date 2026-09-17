"""
Ingest documents using CHARACTER splitting.

Chunks are cut at fixed character intervals (no respect for sections,
code blocks, or tables). Use this to demonstrate poor RAG quality,
then delete chroma_data/ and run 02_ingest.py (semantic) to compare.

Usage:
    python demo/02_ingest_char.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    CHAR_CHUNK_OVERLAP,
    CHAR_CHUNK_SIZE,
    CHROMA_PATH,
    COLLECTION_NAME,
    DOCS_PATH,
    EMBED_MODEL,
)
from chunking.character_splitter import split_by_characters
from vectorstore.embedder import embed_chunks, load_embedding_model
from vectorstore.store import get_or_create_collection, upsert_chunks


def main() -> None:
    md_files = sorted([
        os.path.join(DOCS_PATH, f)
        for f in os.listdir(DOCS_PATH)
        if f.endswith(".md")
    ])
    print(f"Found {len(md_files)} document(s): {[os.path.basename(f) for f in md_files]}\n")

    all_chunks = []
    for doc_path in md_files:
        doc_title = os.path.basename(doc_path)
        with open(doc_path, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = split_by_characters(text, doc_title, CHAR_CHUNK_SIZE, CHAR_CHUNK_OVERLAP)
        print(f"  {doc_title}: {len(chunks)} character chunks")
        all_chunks.extend(chunks)

    print(f"\nTotal chunks to embed: {len(all_chunks)}")

    model = load_embedding_model(EMBED_MODEL)
    embeddings = embed_chunks(all_chunks, model)
    collection = get_or_create_collection(CHROMA_PATH, COLLECTION_NAME)
    upsert_chunks(collection, all_chunks, embeddings)

    print(f"\nIngestion complete (character splitting):")
    print(f"  Documents processed : {len(md_files)}")
    print(f"  Total chunks stored : {len(all_chunks)}")
    print(f"  ChromaDB path       : ./{CHROMA_PATH}")


if __name__ == "__main__":
    main()
