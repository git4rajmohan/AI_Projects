"""Chat area: history, grounded answer, sources, debug trace (§30, §31).

History lives in ``st.session_state.messages``; each answer is produced by the
existing :class:`LlamaIndexEngine` — no retrieval logic here.
"""

from __future__ import annotations

import streamlit as st

from app.config.settings import Settings
from app.retrieval.llamaindex_engine import LlamaIndexEngine, RetrievalResult
from app.ui.components import friendly_error, render_debug, render_sources


def _get_engine(settings: Settings, strategy: str) -> LlamaIndexEngine:
    """One engine per (settings, strategy) pair for the session lifetime."""
    key = f"engine_{strategy}"
    if key not in st.session_state:
        st.session_state[key] = LlamaIndexEngine(settings, strategy=strategy)
    engine: LlamaIndexEngine = st.session_state[key]
    return engine


def render_chat(settings: Settings, debug_mode: bool) -> None:
    """Main chat column. Answers are grounded; sources come from evidence only."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask about the enterprise documents…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            strategy = st.session_state.get("strategy", "hybrid")
            try:
                result = _get_engine(settings, strategy).answer(prompt)
                if result.refused:
                    # §11 enforcement: pre-LLM refusal — show it as a notice,
                    # not a normal answer, so users see the gate is mechanical.
                    st.info(result.answer)
                    if debug_mode:
                        st.caption(f"Gate: {result.refusal_reason}")
                else:
                    st.markdown(result.answer)
                    render_sources(result)
                if debug_mode:
                    render_debug(result, strategy)
                st.session_state.messages.append(
                    {"role": "assistant", "content": result.answer}
                )
                st.session_state.last_result = result
            except Exception as exc:  # noqa: BLE001 — friendly message, real probes
                st.error(friendly_error(exc, settings))

    # Re-show the last answer's evidence under the latest assistant message.
    if st.session_state.get("last_result") and debug_mode:
        with st.expander("🐞 Last answer — debug trace"):
            render_debug(st.session_state.last_result, st.session_state.get("strategy", "hybrid"))


# NOTE: the live "Example questions" expander is rendered by app/main.py
# (click-to-copy st.code blocks, tagged by retrieval leg). This module no
# longer duplicates it — see main.py's render_controls_sidebar.