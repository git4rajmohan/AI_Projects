"""Streamlit entry point — wires settings, sidebar, and chat (Phase 11).

Settings and services are loaded once per session (§35: startup detects
existing state and reuses it — nothing is reprocessed on rerun).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

import streamlit as st

from app.config.settings import PROJECT_ROOT, get_settings

# Windows consoles default to cp1252; tests/logs elsewhere already reconfigure.
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — cosmetic only
        pass

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Enterprise Knowledge Assistant", layout="wide")


def main() -> None:
    settings = get_settings()  # raises ConfigurationError early if .env is broken
    logger.info("Application started (provider=%s, llm=%s)", settings.provider, settings.llm_model)

    from app.ui.chat import render_chat
    from app.ui.sidebar import render_sidebar

    render_sidebar(settings)
    render_controls_sidebar(settings)

    st.title("Enterprise Knowledge Assistant")
    st.caption("Local RAG over enterprise documents — grounded answers with citations.")

    debug_mode = st.session_state.get("debug_mode", False)
    render_chat(settings, debug_mode)


def render_controls_sidebar(settings) -> None:
    """Sidebar controls BELOW the render_sidebar sections (§30 layout).

    Everything configurable lives on the left; the main area stays a clean
    question → answer flow. State keys match what render_chat reads.
    """
    with st.sidebar.expander("⚙️ Retrieval options", expanded=True):
        st.session_state.strategy = st.radio(
            "Retrieval strategy",
            ("hybrid", "vector"),
            index=0,
            help=(
                "Hybrid = document chunks + knowledge-graph relationships; "
                "vector = document chunks only."
            ),
            horizontal=True,
        )
    with st.sidebar.expander("🐞 Example questions"):
        st.caption("Click-to-copy demo questions from the indexed corpus:")
        for tag, question in (
            ("semantic", "How many annual leave days do employees receive?"),
            ("keyword", "What is policy ACME-HR-002?"),
            ("semantic", "What are the rules for remote work?"),
            ("semantic", "What expenses require approval?"),
            ("semantic", "What security requirements apply to employees working remotely?"),
            ("graph", "How are remote work and information security related?"),
            ("refusal", "What is the company's private jet travel policy?"),
        ):
            st.caption(f"[{tag}]")
            st.code(question, language=None)
    with st.sidebar.expander("🧠 Knowledge graph view"):
        _render_graph_view(settings)
    st.session_state.debug_mode = st.sidebar.toggle(
        "Developer / debug mode", value=False, help="Shows the full retrieval trace under each answer."
    )


def _render_graph_view(settings) -> None:
    """Sidebar graph-view section: guidance + open button + rebuild.

    The export itself must run OUTSIDE Streamlit (Ladybug .lbug file lock,
    Error 33) — the rebuild button shells out to the script, which fails while
    the app holds graph handles; hence the explicit guidance on failure.
    """
    graph_html = settings.data_dir / "graph_visualization.html"

    st.markdown(
        "**What is this?**  \n"
        "A map of everything the assistant "
        "learned from your 11 PDFs — not the documents themselves. "
        "After ingestion, Cognee turned each document into **chunks** "
        "(passages), extracted **entities** (people, policies, concepts), and "
        "connected them with labelled **relationships** (e.g. "
        "*remote work policy ── is_a ──➝ policy*)."
    )
    st.markdown(
        "**How to read it**  \n"
        "• Columns = node kinds: 📄 Documents → ✂️ Chunks → 🔷 Entities → "
        "🏷️ Types (left to right).  \n"
        "• A line between two dots is a relationship; hover a dot for its "
        "name, click it for source + provenance.  \n"
        "• Big/bright dots appear in more answers (higher importance).  \n"
        "• **Search** jumps to a node; **Story/Flow/Force** re-arrange the "
        "same graph; **Schema** shows node kinds only."
    )
    st.caption(
        "Layout takes up to ~2 min (1,394 connections). "
        "Answers cite documents; this map shows the concept links."
    )

    if graph_html.exists():
        # Serve via Streamlit's static folder (real same-origin URL), NOT
        # components.html/iframe — cognee's viz stalls at "Laying out 0%"
        # inside ANY iframe (srcdoc crashes on history.replaceState) but
        # works perfectly as a top-level page (verified 2026-09-09).
        # Streamlit 1.63 serves files from <app dir>/static at /app/static/... .
        static_dir = Path(__file__).resolve().parent / "static"
        static_dir.mkdir(exist_ok=True)
        static_file = static_dir / "graph_visualization.html"
        if not static_file.exists() or static_file.stat().st_mtime < graph_html.stat().st_mtime:
            shutil.copyfile(graph_html, static_file)
        st.link_button("🕸️ Open graph view", "app/static/graph_visualization.html", use_container_width=True)
        st.caption("Opens in a new browser tab (full-page interactive view).")
    else:
        st.info("No graph visualization yet — export it first:")

    if st.button("🔄 Rebuild graph view", use_container_width=True):
        if graph_html.exists():
            graph_html.unlink()
        with st.spinner("Exporting graph (takes ~1–2 min, opens no browser)…"):
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "visualize_graph.py"),
                    "--no-open",
                ],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(PROJECT_ROOT),
            )
        if graph_html.exists():
            st.success(f"Graph exported ({graph_html.stat().st_size / 1024:.0f} KB)")
            st.rerun()
        else:
            st.error(
                "Export failed — stop this app and run "
                "`scripts\\visualize_graph.py` manually (Ladybug file lock)."
            )


if __name__ == "__main__":
    main()