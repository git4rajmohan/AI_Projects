import os
from typing import List

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from chunking.character_splitter import Chunk
from config.settings import EMBED_BASE_URL

load_dotenv()


class EmbeddingModel:
    """
    Embedding model backed by any OpenAI-compatible /v1/embeddings endpoint
    (local Ollama by default). Exposes .encode(texts) returning a 2-D numpy
    array, mirroring the SentenceTransformer interface previously used here.
    """

    def __init__(self, client: OpenAI, model_name: str) -> None:
        self._client = client
        self.name = model_name

    def encode(self, texts: List[str]) -> np.ndarray:
        response = self._client.embeddings.create(model=self.name, input=texts)
        return np.array([item.embedding for item in response.data], dtype=float)


def load_embedding_model(model_name: str) -> EmbeddingModel:
    """
    Create an embedding client pointed at the OpenAI-compatible endpoint in
    config.settings.EMBED_BASE_URL (local Ollama by default).
    Called once at ingest time and once at query time.
    """
    # Local Ollama ignores the key; 'ollama' is the documented placeholder.
    api_key = os.getenv("OLLAMA_API_KEY") or "ollama"
    return EmbeddingModel(OpenAI(base_url=EMBED_BASE_URL, api_key=api_key), model_name)


def embed_chunks(chunks: List[Chunk], model: EmbeddingModel) -> List[List[float]]:
    """
    Embed a list of Chunk objects and return a list of embedding vectors.
    Each vector corresponds to the Chunk at the same index.
    Prints embedding progress: 'Embedding X chunks with model Y...'
    """
    print(f"Embedding {len(chunks)} chunks with model {model.name}...")
    embeddings = model.encode([chunk.content for chunk in chunks])
    return [emb.tolist() for emb in embeddings]
