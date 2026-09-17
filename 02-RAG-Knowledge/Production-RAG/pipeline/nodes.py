from config.settings import CHROMA_PATH, COLLECTION_NAME, EMBED_MODEL, TOP_K
from generation.answer_generator import generate
from generation.prompt_builder import build_prompt
from pipeline.state import RAGState
from retrieval.hybrid_search import search
from vectorstore.embedder import load_embedding_model
from vectorstore.store import load_collection


def retrieve_node(state: RAGState) -> dict:
    """
    Load the ChromaDB collection.
    Load the embedding model.
    Run hybrid_search.search() with query from state.
    Return: {"retrieved_chunks": [...]}
    On error: return {"error": "Retrieval failed: <message>"}
    """
    try:
        collection = load_collection(CHROMA_PATH, COLLECTION_NAME)
        model = load_embedding_model(EMBED_MODEL)
        chunks = search(state["query"], collection, model, TOP_K)
        return {"retrieved_chunks": chunks}
    except Exception as exc:
        return {"error": f"Retrieval failed: {exc}"}


def build_prompt_node(state: RAGState) -> dict:
    """
    Call prompt_builder.build_prompt() with query and retrieved_chunks from state.
    Return: {"prompt": <PromptMessages>}
    On error: return {"error": "Prompt build failed: <message>"}
    """
    try:
        prompt = build_prompt(state["query"], state["retrieved_chunks"])
        return {"prompt": prompt}
    except Exception as exc:
        return {"error": f"Prompt build failed: {exc}"}


def generate_node(state: RAGState) -> dict:
    """
    Call answer_generator.generate() with prompt from state.
    Return: {"answer": <Answer>}
    On error: return {"error": "Generation failed: <message>"}
    """
    try:
        answer = generate(state["prompt"], state["query"], len(state["retrieved_chunks"]))
        return {"answer": answer}
    except Exception as exc:
        return {"error": f"Generation failed: {exc}"}
