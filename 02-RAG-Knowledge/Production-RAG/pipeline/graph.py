from langgraph.graph import END, START, StateGraph

from generation.answer_generator import Answer
from pipeline.nodes import build_prompt_node, generate_node, retrieve_node
from pipeline.state import RAGState


def _route_after_retrieve(state: RAGState) -> str:
    """Route to END if retrieval errored, otherwise continue to build_prompt_node."""
    if state.get("error"):
        return END
    return "build_prompt_node"


def build_rag_graph():
    """
    Build and compile the LangGraph StateGraph:
    START → retrieve_node → build_prompt_node → generate_node → END
    Adds a conditional edge after retrieve_node: if state["error"] is not empty,
    routes directly to END instead of continuing.
    Returns the compiled graph.
    """
    graph = StateGraph(RAGState)

    graph.add_node("retrieve_node", retrieve_node)
    graph.add_node("build_prompt_node", build_prompt_node)
    graph.add_node("generate_node", generate_node)

    graph.add_edge(START, "retrieve_node")
    graph.add_conditional_edges("retrieve_node", _route_after_retrieve)
    graph.add_edge("build_prompt_node", "generate_node")
    graph.add_edge("generate_node", END)

    return graph.compile()


def run_query(query: str) -> Answer:
    """
    Build the graph, invoke it with initial state {"query": query, "error": ""},
    and return the Answer from the final state.
    If state["error"] is not empty after the run, raise RuntimeError(state["error"]).
    """
    rag_graph = build_rag_graph()
    initial_state: dict = {
        "query": query,
        "retrieved_chunks": [],
        "prompt": None,
        "answer": None,
        "error": "",
    }
    final_state = rag_graph.invoke(initial_state)

    if final_state.get("error"):
        raise RuntimeError(final_state["error"])

    return final_state["answer"]
