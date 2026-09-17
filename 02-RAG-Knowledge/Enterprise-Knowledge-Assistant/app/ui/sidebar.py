"""Streamlit sidebar: documents, upload, processing, status, clear (§30, §36, §53).

All actions delegate to the existing managers — DocumentManager for inventory/
upload safety, CognifyManager for processing (the sole ingestion path,
ledger-protected so unchanged files are never reprocessed), cognee.forget for
the destructive clear.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import streamlit as st

from app.config.settings import Settings
from app.ingestion.document_manager import SUPPORTED_EXTENSIONS, DocumentManager
from app.knowledge.cognee_manager import CognifyManager
from app.vectorstore import qdrant_manager

logger = logging.getLogger(__name__)


def _safe_filename(name: str, document_dir: Path) -> str | None:
    """Sanitize an upload name to a plain filename under document_dir (§53).

    Strips any path components and unsafe characters; returns None when the
    result would be empty or would overwrite something outside document_dir.
    """
    base = Path(name).name  # kill any directory traversal
    base = re.sub(r"[^A-Za-z0-9._\- ]", "_", base).strip()
    if not base or base.startswith("."):
        return None
    resolved = (document_dir / base).resolve()
    return str(resolved) if resolved.parent == document_dir.resolve() else None


def render_sidebar(settings: Settings) -> None:
    """Sidebar sections per §30: Documents / System Status / Configuration."""
    st.sidebar.title("Enterprise Knowledge Assistant")

    with st.sidebar.expander("Documents", expanded=True):
        manager = DocumentManager(settings.document_dir, settings.metadata_dir)

        # Self-heal: regenerate the metadata store if it was wiped (e.g. by a
        # reset that kept the PDFs). sync() only hashes files on disk — it
        # never triggers Cognee ingestion, so this is instant and safe.
        manager.sync()

        # -- upload (§53: allowlist + sanitized filenames) ----------------
        uploads = st.file_uploader(
            "Upload documents",
            type=[ext.lstrip(".") for ext in sorted(SUPPORTED_EXTENSIONS)],
            accept_multiple_files=True,
        )
        if uploads:
            saved = []
            for upload in uploads:
                safe_path = _safe_filename(upload.name, settings.document_dir)
                if safe_path is None:
                    st.warning(f"Rejected unsafe filename: {upload.name}")
                    continue
                Path(safe_path).write_bytes(upload.getvalue())
                saved.append(safe_path)
            if saved:
                counts = manager.sync()
                st.success(f"Saved {len(saved)} file(s). New: {counts['added']}, duplicates: {counts['duplicates']}")
                st.rerun()

        # -- process (§17: real counts, never fabricated) ------------------
        if st.button("Process documents"):
            paths = [Path(m.source_path) for m in manager.inventory()]
            with st.spinner("Processing via Cognee (LLM extraction — can take minutes)…"):
                result = CognifyManager(settings).ingest_all(paths)
            if result["new"] == 0:
                st.info(f"Nothing to process — {result['skipped_duplicates']} file(s) already indexed.")
            else:
                st.success(
                    f"Documents processed: {result['processed']}\n\n"
                    f"Skipped (already indexed): {result['skipped_duplicates']}\n\n"
                    "See logs for graph/vector counts."
                )
            st.rerun()

        # -- document list -------------------------------------------------
        docs = manager.load_all()
        if docs:
            st.markdown(f"**Indexed documents ({len(docs)})**")
            for name in sorted(docs):
                st.markdown(f"- 📄 `{name}`")
        else:
            st.caption("No documents indexed yet.")

        # -- clear knowledge base (§36, confirmation required) -------------
        with st.popover("🗑️ Clear knowledge base"):
            st.warning(
                "Deletes all vectors, the Cognee knowledge graph, and metadata. "
                "Source PDFs in data/documents are kept."
            )
            if st.button("Yes, clear everything", type="primary"):
                CognifyManager(settings).reset()
                for meta_file in ("ingested.json", "documents.json"):
                    path = settings.metadata_dir / meta_file
                    if path.exists():
                        path.unlink()
                logger.info("Knowledge base cleared (vectors, graph, metadata)")
                st.success("Knowledge base cleared. Source documents kept.")
                st.rerun()

    st.sidebar.divider()
    with st.sidebar.expander("System Status"):
        from app.ui.components import render_system_status

        render_system_status(settings)

    st.sidebar.divider()
    with st.sidebar.expander("Configuration"):
        st.markdown(
            f"**LLM:** `{settings.llm_model}` ({settings.provider})\n\n"
            f"**Embedding:** `{settings.embed_model}` (local)\n\n"
            f"**Top K:** {settings.top_k}"
        )