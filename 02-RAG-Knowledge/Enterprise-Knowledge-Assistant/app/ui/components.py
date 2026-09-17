"""Shared Streamlit widgets: real health status, citations, debug panel, errors.

Phase 11 (instructions.md §30–§33). Every value shown is REAL — health comes
from ``scripts/check_services.py`` (reused, not re-implemented), citations come
from retrieved evidence, and errors are diagnosed with real probes before a
friendly message is chosen.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import requests
import streamlit as st

from app.config.settings import Settings
from app.retrieval.llamaindex_engine import RetrievalResult
from app.retrieval.vector_retriever import CHUNK_COLLECTION
from app.vectorstore import qdrant_manager

# scripts/ is not a package; put the project root on sys.path so the Phase 1
# health-check module (the single source of truth for service checks) imports.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.check_services import run_all_checks  # noqa: E402

logger = logging.getLogger(__name__)

_GREEN, _RED = "🟢", "🔴"


# --------------------------------------------------------------------- #
# System status (§32)                                                    #
# --------------------------------------------------------------------- #
def cognee_status(settings: Settings) -> tuple[bool, str]:
    """Real Cognee readiness: can we read the knowledge graph right now?"""
    try:
        from app.knowledge.cognee_manager import CognifyManager

        status = CognifyManager(settings).get_status()
    except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
        return False, f"{type(exc).__name__}: {exc}"
    graph = status.get("graph", {})
    if "error" in graph:
        return False, str(graph["error"])
    return True, (
        f"Ready — {graph.get('nodes', 0)} nodes / {graph.get('relationships', 0)} relationships"
    )


def knowledge_status(settings: Settings) -> tuple[bool, str]:
    """Real indexed-state probe: chunk collection exists and holds points."""
    del settings  # collection name is fixed by the Cognee adapter, not config
    try:
        info = qdrant_manager.get_collection_info(CHUNK_COLLECTION)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if not info:
        return False, "not indexed yet (no chunk collection)"
    return True, f"Indexed — {info['points_count']} chunks"


def render_system_status(settings: Settings) -> None:
    """§32 status lines. Checks are real and cached per session; Re-check re-runs.

    UX contract: a full check cycle takes ~10-20 s (cloud-LLM ping + Cognee
    graph init), so (1) a spinner is shown while checks run, (2) previous
    results stay visible during a re-check (stale-while-revalidate — a click
    must never blank the panel), and (3) results are always cached, even when
    every check is red.
    """
    recheck = st.button("Re-check services")
    cached = st.session_state.get("health")
    if cached:
        for name, ok, detail in cached:
            st.markdown(f"{_GREEN if ok else _RED} **{name}** — {detail}")
    if recheck or cached is None:
        with st.spinner("Running health checks (cloud-LLM ping can take ~10-20 s)…"):
            _, results = run_all_checks(parallel=True)
            results.append(("Cognee", *cognee_status(settings)))
            results.append(("Knowledge base", *knowledge_status(settings)))
        st.session_state.health = results
        st.rerun()  # swap stale lines for the fresh ones cleanly


# --------------------------------------------------------------------- #
# Citations + debug panel (§27, §31)                                     #
# --------------------------------------------------------------------- #
def render_sources(result: RetrievalResult) -> None:
    """§27 — filenames from retrieved evidence only, never from the LLM."""
    if not result.citations:
        return
    with st.expander("Sources"):
        for citation in result.citations:
            page = f" — Page {citation.page}" if citation.page else ""
            st.markdown(f"📄 `{citation.document}`{page}")


def render_debug(result: RetrievalResult, strategy: str) -> None:
    """§31 developer block — the full pipeline trace for one answer."""
    with st.expander("🐞 Debug — retrieval trace", expanded=False):
        st.markdown(f"**Query**\n\n{result.query}")
        st.markdown(f"**Retrieval Strategy**\n\n{strategy}")
        if result.refused:
            st.markdown(
                f"**⚠️ Evidence gate: REFUSED** — {result.refusal_reason}. "
                "The LLM was not called."
            )

        st.markdown("**Vector Results**")
        if result.vector_hits:
            for i, hit in enumerate(result.vector_hits, 1):
                st.markdown(f"{i}. `{hit.document}` — score `{hit.score:.3f}` — chunk `{hit.chunk_id}`")
        else:
            st.caption("none")

        st.markdown("**BM25 Results** (keyword leg)")
        if result.bm25_hits:
            for i, hit in enumerate(result.bm25_hits, 1):
                st.markdown(f"{i}. `{hit.document}` — BM25 `{hit.score:.3f}` — chunk `{hit.chunk_id}`")
        elif result.bm25_error:
            st.caption(f"failed: {result.bm25_error}")
        else:
            st.caption("none")

        st.markdown("**RRF Fusion** (context order)")
        if result.fused_hits:
            for i, hit in enumerate(result.fused_hits, 1):
                legs = "+".join(hit.contributed_by)
                agree = " ✔" if hit.both_legs_agree else ""
                st.markdown(
                    f"{i}. `{hit.document}` — RRF `{hit.rrf_score:.4f}` — {legs}{agree} — chunk `{hit.chunk_id}`"
                )
        else:
            st.caption("none")

        st.markdown("**Graph Entities / Relationships**")
        if result.graph_hits:
            entities = {h.subject for h in result.graph_hits} | {h.object for h in result.graph_hits}
            for name in sorted(entities):
                st.markdown(f"- {name}")
            for hit in result.graph_hits:
                st.markdown(f"- `{hit.subject}` ──{hit.relationship}──> `{hit.object}`")
        else:
            st.caption("none")

        st.markdown("**Evidence** (truncated)")
        for i, hit in enumerate(result.vector_hits, 1):
            st.text(f"[{i}] {hit.text[:400]}")
        for i, hit in enumerate(result.graph_hits, 1):
            st.text(f"[G{i}] {hit.to_text()}")

        st.markdown("**Sources**")
        for document in result.sources:
            st.markdown(f"- 📄 `{document}`")

        st.markdown("**Final Prompt Context**")
        st.code(result.context or "(not recorded)")

        st.markdown("**LLM Response**")
        st.text(result.answer)


# --------------------------------------------------------------------- #
# Friendly errors (§33)                                                  #
# --------------------------------------------------------------------- #
def friendly_error(exc: Exception, settings: Settings) -> str:
    """Diagnose with REAL probes, then return the matching §33 user message.

    Full detail goes to the logs only — never a stack trace in the normal UI.
    """
    logger.error("UI action failed", exc_info=exc)
    text = str(exc)
    if "Collection" in text and "does not exist" in text:
        return (
            "No documents are indexed yet.\n\n"
            "Upload documents in the sidebar and press **Process documents**."
        )
    if not qdrant_manager.health_check().get("ok"):
        return (
            "Qdrant is unavailable.\n\n"
            f"Please verify that Qdrant is running on {settings.qdrant_url}."
        )
    try:
        requests.get(f"{settings.local_base_url.rstrip('/')}/api/tags", timeout=3)
    except Exception:  # noqa: BLE001
        return "Ollama is not running.\n\nPlease start Ollama and try again."
    embed_ok, embed_detail = _check_embed_model(settings.local_base_url, settings.embed_model)
    if not embed_ok:
        return f"The configured embedding model is unavailable.\n\n{embed_detail}"
    return "Something went wrong while processing the request. Details are in the application logs."