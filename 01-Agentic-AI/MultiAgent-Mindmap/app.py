"""Streamlit app: AI Mindmap Creator.

Takes text files, YouTube URLs, or pasted text, sends the content to a local
Ollama LLM which produces a Markdown hierarchy, then renders an interactive
markmap mindmap in the browser.
"""

import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

from src.input_handler import extract_from_file, extract_from_text, extract_from_youtube
from src.mindmap_generator import generate_mindmap
from src.agent_pipeline import run_agent_pipeline
from src.renderer import render_to_html, save_html

load_dotenv()

# ─── Page config ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Mindmap Creator",
    page_icon="🧠",
    layout="wide",
)


# ─── Helpers ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def fetch_ollama_models(base_url: str) -> list[str]:
    """Fetch available model names from Ollama's /api/tags endpoint."""
    # base_url is like http://localhost:11434/v1 — strip /v1 for /api/tags
    tags_url = base_url.rstrip("/").removesuffix("/v1") + "/api/tags"
    try:
        resp = requests.get(tags_url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def check_ollama_running(base_url: str) -> bool:
    """Quick health check — can we reach Ollama?"""
    tags_url = base_url.rstrip("/").removesuffix("/v1") + "/api/tags"
    try:
        resp = requests.get(tags_url, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


# ─── Sidebar ──────────────────────────────────────────────────────────────
st.sidebar.title("⚙️ Settings")

default_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
ollama_base_url = st.sidebar.text_input(
    "Ollama Base URL",
    value=default_base_url,
    help="Your local Ollama API endpoint (default: http://localhost:11434/v1)",
)

# Health check
if check_ollama_running(ollama_base_url):
    st.sidebar.success("✅ Ollama is running")
else:
    st.sidebar.error("❌ Ollama is not reachable. Start it with `ollama serve`.")

# Model selection
available_models = fetch_ollama_models(ollama_base_url)
default_model = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")

if available_models:
    # Try to preselect the default model if it's in the list
    try:
        default_index = available_models.index(default_model)
    except ValueError:
        default_index = 0
    selected_model = st.sidebar.selectbox(
        "Model",
        available_models,
        index=default_index,
        help="Choose an Ollama model to generate the mindmap",
    )
else:
    selected_model = st.sidebar.text_input(
        "Model (manual entry)",
        value=default_model,
        help="No models detected. Enter the model name manually.",
    )

st.sidebar.markdown("---")
st.sidebar.markdown(
    "💡 **Tip:** Larger models produce better mindmaps but take longer.\n\n"
    "Pull a model with `ollama pull gpt-oss:120b`"
)


# ─── Main content ─────────────────────────────────────────────────────────
st.title("🧠 AI Mindmap Creator")
st.markdown("Transform text, YouTube transcripts, or pasted content into interactive mindmaps.")

# Top-level mode selection
tab_fast, tab_agent = st.tabs(["⚡ Fast Mode (Single-Pass)", "🤖 Agent Mode (Review Loop)"])

# ─── Shared input component ─────────────────────────────────────────────
def render_input_section(key_prefix=""):
    """Render the shared input section (file upload, YouTube, paste text).

    Args:
        key_prefix: Prefix for widget keys to avoid duplicates across tabs.

    Returns (input_text, input_label) or (None, "").
    """
    sub_file, sub_youtube, sub_text = st.tabs(["📁 Upload File", "▶️ YouTube URL", "✏️ Paste Text"])

    input_text = None
    input_label = ""

    with sub_file:
        uploaded_file = st.file_uploader(
            "Upload a text file",
            type=["txt", "md"],
            help="Supported formats: .txt, .md",
            key=f"{key_prefix}file_uploader",
        )
        if uploaded_file is not None:
            input_text = extract_from_file(uploaded_file)
            input_label = uploaded_file.name
            word_count = len(input_text.split())
            st.info(f"📄 Loaded: **{uploaded_file.name}** ({word_count:,} words)")

    with sub_youtube:
        youtube_url = st.text_input(
            "YouTube URL",
            placeholder="https://www.youtube.com/watch?v=...",
            help="Paste a YouTube video URL. The transcript will be fetched automatically.",
            key=f"{key_prefix}youtube_url",
        )
        if youtube_url:
            try:
                with st.spinner("Fetching transcript..."):
                    input_text = extract_from_youtube(youtube_url)
                    input_label = "YouTube transcript"
                    word_count = len(input_text.split())
                    st.info(f"▶️ Transcript fetched ({word_count:,} words)")
            except ValueError as e:
                st.error(f"Could not parse URL: {e}")
            except Exception as e:
                st.error(f"Could not fetch transcript: {e}")

    with sub_text:
        pasted_text = st.text_area(
            "Paste your text here",
            height=200,
            placeholder="Paste any text you want to convert into a mindmap...",
            key=f"{key_prefix}pasted_text",
        )
        if pasted_text.strip():
            input_text = extract_from_text(pasted_text)
            input_label = "Pasted text"
            word_count = len(input_text.split())
            st.info(f"✏️ Text loaded ({word_count:,} words)")

    return input_text, input_label


def render_results(markdown_output, session_key="markdown_output"):
    """Render the mindmap display, edit expander, and download buttons."""
    st.markdown("---")
    st.subheader("🗺️ Mindmap")

    html_content = render_to_html(markdown_output)
    st.components.v1.html(html_content, height=700, scrolling=False)

    with st.expander("📝 View / Edit Markdown (re-renders on change)"):
        edited_markdown = st.text_area(
            "Markdown",
            value=markdown_output,
            height=300,
            label_visibility="collapsed",
            key=f"edit_{session_key}",
        )
        if edited_markdown != markdown_output:
            st.session_state[session_key] = edited_markdown
            edited_html = render_to_html(edited_markdown)
            st.components.v1.html(edited_html, height=700, scrolling=False)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="⬇️ Download HTML",
            data=html_content.encode("utf-8"),
            file_name="mindmap.html",
            mime="text/html",
            help="Download a standalone HTML file you can open in any browser",
            key=f"dl_html_{session_key}",
        )
    with col2:
        st.download_button(
            label="⬇️ Download Markdown",
            data=markdown_output.encode("utf-8"),
            file_name="mindmap.md",
            mime="text/markdown",
            help="Download the Markdown source",
            key=f"dl_md_{session_key}",
        )


# ─── Fast Mode tab ───────────────────────────────────────────────────────
with tab_fast:
    st.markdown("**Single LLM call** — fast (~30s), good for simple content.")
    input_text, input_label = render_input_section(key_prefix="fast_")

    st.markdown("---")
    if input_text and input_text.strip():
        if st.button("🚀 Generate Mindmap", type="primary", use_container_width=True, key="btn_fast"):
            with st.spinner(f"Generating mindmap with {selected_model}... (this may take 30-60 seconds)"):
                try:
                    markdown_output = generate_mindmap(
                        text=input_text,
                        model=selected_model,
                        base_url=ollama_base_url,
                    )
                    st.session_state["markdown_output"] = markdown_output
                    st.session_state["input_label"] = input_label
                except Exception as e:
                    st.error(f"Failed to generate mindmap: {e}")
                    st.info("Make sure Ollama is running and the model is pulled. Try `ollama serve` and `ollama list`.")

    if "markdown_output" in st.session_state:
        render_results(st.session_state["markdown_output"])
    elif not input_text or not input_text.strip():
        st.info("👆 Provide some text above (upload a file, paste a YouTube URL, or type text) to get started.")


# ─── Agent Mode tab ──────────────────────────────────────────────────────
with tab_agent:
    st.markdown("**Multi-agent pipeline** — Schema Creator → Reviewer → Mindmap Creator. "
                "Slower (2-5 min) but higher quality for complex content.")
    st.markdown("The schema goes through a review loop until the reviewer approves it, "
                "then the final mindmap is created.")
    agent_input_text, agent_input_label = render_input_section(key_prefix="agent_")

    # Max iterations slider
    max_iter = st.slider(
        "Max review iterations",
        min_value=1,
        max_value=5,
        value=3,
        help="How many times the reviewer can request changes before accepting the schema",
    )

    st.markdown("---")
    if agent_input_text and agent_input_text.strip():
        if st.button("🤖 Run Agent Pipeline", type="primary", use_container_width=True, key="btn_agent"):
            # Create a status container for live progress updates
            status_container = st.empty()
            progress_lines = []

            def update_progress(msg):
                progress_lines.append(msg)
                status_container.markdown("\n\n".join(progress_lines))

            try:
                with st.spinner("Running agent pipeline..."):
                    result = run_agent_pipeline(
                        text=agent_input_text,
                        model=selected_model,
                        base_url=ollama_base_url,
                        max_iterations=max_iter,
                        progress_callback=update_progress,
                    )

                # Show final status
                status_container.markdown("\n\n".join(progress_lines))

                # Store results in session state
                st.session_state["agent_markdown_output"] = result["markdown"]
                st.session_state["agent_schema"] = result["schema"]
                st.session_state["agent_review_history"] = result["review_history"]
                st.session_state["agent_iterations"] = result["iterations"]
                st.session_state["agent_approved"] = result["approved"]

            except Exception as e:
                st.error(f"Agent pipeline failed: {e}")
                st.info("Make sure Ollama is running and the model is pulled.")

    # Display agent results
    if "agent_markdown_output" in st.session_state:
        # Show pipeline summary
        with st.expander("📊 Pipeline Summary"):
            approved = st.session_state.get("agent_approved", False)
            iterations = st.session_state.get("agent_iterations", 0)
            col_a, col_b = st.columns(2)
            with col_a:
                status_emoji = "✅" if approved else "⚠️"
                st.metric("Status", f"{status_emoji} {'Approved' if approved else 'Max iterations'}")
            with col_b:
                st.metric("Review Iterations", iterations)

            # Show review history
            review_history = st.session_state.get("agent_review_history", [])
            for i, feedback in enumerate(review_history, 1):
                st.markdown(f"**Iteration {i}:** {feedback}")

            # Show the JSON schema
            schema = st.session_state.get("agent_schema", {})
            st.markdown("**Final Schema:**")
            st.json(schema)

        # Render the mindmap
        render_results(st.session_state["agent_markdown_output"], session_key="agent_markdown_output")
    elif not agent_input_text or not agent_input_text.strip():
        st.info("👆 Provide some text above (upload a file, paste a YouTube URL, or type text) to get started.")