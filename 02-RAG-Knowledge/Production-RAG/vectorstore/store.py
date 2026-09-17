from typing import List

import chromadb

from chunking.character_splitter import Chunk


def _serialize_metadata(metadata: dict) -> dict:
    """Convert None values and non-primitive types to strings for ChromaDB compatibility."""
    return {k: (str(v) if v is None else v) for k, v in metadata.items()}


def get_or_create_collection(chroma_path: str, collection_name: str) -> chromadb.Collection:
    """
    Create a PersistentClient pointing to chroma_path.
    Get or create the named collection.
    Print the path so students can see where data is stored.
    """
    print(f"ChromaDB collection at: ./{chroma_path}")
    client = chromadb.PersistentClient(path=chroma_path)
    return client.get_or_create_collection(name=collection_name)


def upsert_chunks(
    collection: chromadb.Collection,
    chunks: List[Chunk],
    embeddings: List[List[float]],
) -> None:
    """
    Insert chunks and their embeddings into the collection.
    Each document ID is: f"{chunk.metadata['doc_title']}_{chunk.metadata['chunk_index']}"
    Store the full metadata dict as ChromaDB metadata.
    Store chunk.content as the document text.
    """
    ids = [
        f"{chunk.metadata['doc_title']}_{chunk.metadata['chunk_index']}"
        for chunk in chunks
    ]
    documents = [chunk.content for chunk in chunks]
    metadatas = [_serialize_metadata(chunk.metadata) for chunk in chunks]

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    print(f"Upserted {len(chunks)} chunks into collection {collection.name}")


def load_collection(chroma_path: str, collection_name: str) -> chromadb.Collection:
    """
    Load an existing ChromaDB collection from disk.
    Raise a clear RuntimeError if the collection does not exist yet.
    """
    try:
        client = chromadb.PersistentClient(path=chroma_path)
        return client.get_collection(name=collection_name)
    except Exception:
        raise RuntimeError("Collection not found. Run demo/02_ingest.py first.")
