"""Probe: does the worker-thread wrapper alone reproduce the server failure?

Mirrors score_snapshot()'s threading pattern exactly, standalone in .venv python.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import nest_asyncio
nest_asyncio.apply()

import threading
import time

from eval.ragas_eval import _run_ragas

SAMPLES = [{
    "row_id": "q1",
    "user_input": "What is RAG?",
    "retrieved_contexts": ["RAG stands for Retrieval-Augmented Generation. "
                           "It combines a retriever with a generator LLM."],
    "response": "RAG is Retrieval-Augmented Generation, combining retrieval with generation.",
    "reference": "Retrieval-Augmented Generation combines retrieval and generation.",
}]

box = {"scores": None, "error": None}


def _worker():
    try:
        box["scores"] = _run_ragas(
            SAMPLES, ["faithfulness"], "glm-5.3-flash",
            "https://ollama.com/v1", "nomic-embed-text",
            "http://localhost:11434/v1", 1, 180, log=print)
    except Exception as exc:
        box["error"] = exc


t0 = time.time()
worker = threading.Thread(target=_worker, daemon=True)
worker.start()
while worker.is_alive():
    worker.join(timeout=2.0)
print("elapsed %.1fs" % (time.time() - t0))
if box["error"]:
    print("FAIL:", type(box["error"]).__name__, box["error"])
else:
    print("scores:", box["scores"])