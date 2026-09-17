import os

from dotenv import load_dotenv

# Load .env before reading env vars so overrides take effect at import time.
load_dotenv()

DOCS_PATH = "docs"
CHROMA_PATH = "chroma_data"
COLLECTION_NAME = "rag_docs"

# ── Chat LLM: Ollama Cloud (OpenAI-compatible) ──
CHAT_BASE_URL = os.getenv("OLLAMA_CHAT_BASE_URL", "https://ollama.com/v1")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gpt-oss:120b")

# ── Embeddings: local Ollama (OpenAI-compatible) ──
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EMBED_BASE_URL = os.getenv("OLLAMA_EMBED_BASE_URL", "http://localhost:11434/v1")

# Chunking
CHAR_CHUNK_SIZE = 500
CHAR_CHUNK_OVERLAP = 50
SEMANTIC_MAX_WORDS = 400      # sections above this trigger H3 splitting

# Retrieval
TOP_K = 5
