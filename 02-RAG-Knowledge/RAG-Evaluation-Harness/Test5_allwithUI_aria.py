# =============================================================================
# RAG Metrics Evaluation UI (no-embedding, LLM-judged)
# =============================================================================
# What this app does, in plain language:
#
#   You have a RAG (Retrieval-Augmented Generation) system — a "chatbot that
#   looks things up before answering". This app helps you measure HOW GOOD
#   that system is, without using any embedding models.
#
#   The app has 3 tabs:
#     1. Config  - You list questions, set the LLM model, and pick metrics.
#     2. Results - You see scores in a dashboard + per-row detail.
#     3. Metric  - You read what each score means and the recommended range.
#
#   The flow is "Step 1 then Step 2":
#     - Step 1: For each question, call your RAG system to get its answer
#               and the documents it retrieved. You can review/edit these.
#     - Step 2: Send the question, answer, retrieved docs, and (optionally)
#               the reference answer to a "judge" LLM, which scores them.
#
#   Scoring is done with the RAGAS library (LLM-judged metrics only, no
#   embeddings), so it works with any OpenAI-compatible chat endpoint.
# =============================================================================


# ----- Standard Python libraries -----
# asyncio     : lets us run multiple LLM calls in parallel / non-blocking
# csv          : load ground-truth Q/A pairs from a CSV file
# html        : safely escape text before showing it on the webpage
# json        : parse JSON replies from the LLM
# os, sys     : read environment variables and tweak Python's import system
# re          : simple text cleanup with regular expressions
# types       : lets us create fake/stub modules on the fly
# dataclasses : a tidy way to define simple data "records" (like rows)
# pathlib     : handle file paths in a clean, cross-platform way
# typing.Any  : a type hint meaning "anything goes"
import asyncio
import csv
import html
import json
import os
import re
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Force UTF-8 on stdout/stderr. On Windows the default codec (cp932) raises
# UnicodeEncodeError when the Aria response contains characters such as the
# em-dash (\u2013) that KB pages routinely include.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

# ----- Third-party libraries -----
# pandas      : used to build editable tables in the UI
# streamlit   : the web UI framework that turns Python into a webpage
# dotenv      : reads settings from the "1.env" file (API keys, URLs, etc.)
# openai      : the official OpenAI client (works with any compatible API)
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from openai import AsyncOpenAI

# ----- Our own helpers (defined in utils.py) -----
# get_llm_response : calls our RAG endpoint with a question and gets back
#                    {"answer": "...", "retrieved_docs": [...]}
# load_test_data   : reads the default test rows from testdata/Test5.json
from utils import get_llm_response, load_test_data

# ----- JSON-file persistence for past evaluation runs -----
# (Lightweight, no DB. See eval_history_io.py for the rationale and
# file layout. Imported as a module so the helpers can be unit-tested
# independently of the Streamlit UI.)
from eval_history_io import (
    delete_run as _history_delete_run,
    history_dir as _history_dir,
    list_runs as _history_list_runs,
    load_run as _history_load_run,
    runs_in_date_range as _history_runs_in_date_range,
    save_run as _history_save_run,
)

# ----- Plotly for the Analytics tab charts -----
import plotly.express as px
import plotly.graph_objects as go


# ---------------------------------------------------------------------------
# Reuse the Aria client from Test1_contextprecisionaria.py.
#
# We import it as a regular module (rather than copy-pasting) so the Aria
# streaming, token handling, and source-fetching logic stays in one place.
# We previously used importlib.util.spec_from_file_location here, but
# Streamlit runs the script via `exec(code, module.__dict__)` which does not
# give the helper a fresh module namespace, so re-execution would fail with
# "module 'test1_contextprecisionaria_module' has no attribute 'AriaClient'".
# A plain `from Test1_contextprecisionaria import ...` works correctly
# because Python reuses the already-cached sys.modules entry.
# ---------------------------------------------------------------------------
from Test1_contextprecisionaria import (
    AriaClient as _AriaClient,
    AriaSource as _AriaSource,
    AriaAnswerPayload as _AriaAnswerPayload,
    fetch_aria_answer_payload as _fetch_aria_answer_payload,
    CONFIG as _T1_CONFIG,
)
# Public aliases used by the rest of this file.
AriaClient = _AriaClient
AriaSource = _AriaSource
AriaAnswerPayload = _AriaAnswerPayload
fetch_aria_answer_payload = _fetch_aria_answer_payload
TOP_CONTEXT_COUNT = _T1_CONFIG.top_context_count
SOURCE_FETCH_TIMEOUT_SECONDS = _T1_CONFIG.__class__.__module__  # placeholder, not used


# Project root directory (parent of this script). Used to resolve paths to
# data files such as testdata/ARIA_data.csv.
PROJECT_DIR = Path(__file__).resolve().parent

# Path to the file that holds secrets and settings (API key, base URLs, etc.)
ENV_FILE = PROJECT_DIR / "1.env"

# Path to the Aria-based test data CSV (question, reference). Used by both
# the Streamlit UI (when ARIA_DATA_FILE is set) and the CLI runner.
ARIA_DATA_FILE = PROJECT_DIR / "testdata" / "ARIA_data.csv"

# These are URL endings we want to strip off if a user pastes a full
# chat-completions URL into the "base URL" field, so the OpenAI client
# can build correct request URLs underneath.
OPENAI_COMPLETION_SUFFIXES = ("/chat/completions", "/completions")

# --- LLM provider presets --------------------------------------------------
# All three providers expose an OpenAI-compatible /v1/chat/completions
# endpoint, so the same client code works for every entry below. The
# sidebar helper `render_provider_sidebar()` lets you switch between them
# from the UI and pre-fills the LLM endpoint + model in the Config form.
# The API key is always read from the env (1.env) for security — the
# sidebar never echoes or writes it.
LLM_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "Custom (manual)": {
        "endpoint": "",
        "model": "",
        "help": "Type your own endpoint and model below.",
    },
    "Ollama (local)": {
        "endpoint": "http://localhost:11434/v1",
        "model": "llama3.1:8b",
        "help": "Local Ollama daemon. Any non-empty OPENAI_API_KEY works (e.g. 'ollama').",
    },
    "Baseten": {
        "endpoint": "https://api.baseten.co/v1",
        "model": "",
        "help": "Hosted models on Baseten. Model is your deployment id; set OPENAI_API_KEY in 1.env.",
    },
    "OpenAI": {
        "endpoint": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "help": "OpenAI's hosted API. Set OPENAI_API_KEY in 1.env to your sk-... key.",
    },
    "Azure OpenAI": {
        "endpoint": "https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT",
        "model": "",
        "help": "Azure OpenAI deployment. Set OPENAI_API_KEY in 1.env and update the URL with your resource + deployment names.",
    },
}

# Default test data file (questions + reference answers) loaded into the UI.
TEST_DATA_FILE = "Test5.json"

# Metrics are grouped by the RAG stage they evaluate. This list is the
# "single source of truth" for what metrics exist, in what order, and
# which stage of the RAG pipeline each one belongs to.
METRIC_GROUPS = [
    (
        "Retrieval Area",
        [
            "Context relevance",
            "Context precision with reference",
            "Context recall",
        ],
    ),
    (
        "Augmentation Area",
        [
            "Response groundedness",
            "Faithfulness",
        ],
    ),
    (
        "Generation Area",
        [
            "Factual correctness",
            "Rubrics score",
        ],
    ),
]
# Flat list of every metric, just unpacked from METRIC_GROUPS above.
# Used for the "select metrics" dropdown in the UI.
AVAILABLE_METRICS = [metric_name for _, metric_names in METRIC_GROUPS for metric_name in metric_names]

# Some metrics need extra data to do their job. These sets tell the UI
# which inputs are required so we can warn the user before they run.
# For example, "Faithfulness" needs the model's response, so we check
# that the response field is filled in before running.
METRICS_REQUIRING_RESPONSE = {"Faithfulness", "Response groundedness", "Factual correctness", "Rubrics score"}
METRICS_REQUIRING_REFERENCE = {"Context precision with reference", "Context recall", "Factual correctness", "Rubrics score"}
METRICS_REQUIRING_CONTEXTS = {
    "Context relevance",
    "Context precision with reference",
    "Context recall",
    "Response groundedness",
    "Faithfulness",
}

# "Rubrics score" is the most user-facing metric (a 1-5 rating with a
# human description per level) so it is ALWAYS selected — the user can
# edit the rubric text in the Config tab but cannot turn the metric off.
ALWAYS_SELECTED_METRICS = ("Rubrics score",)

# All available rubric presets, keyed by display name. The judge LLM is
# given the chosen preset's level descriptions and picks the one that
# best matches the response. Users can also edit any level after picking
# a preset; their edits live in st.session_state["rubrics"] and take
# precedence over the preset.
RUBRIC_PRESETS: dict[str, dict[str, str]] = {
    "Factual QA Rubric": {
        "score1_description": "The response is incorrect, irrelevant, or does not align with the ground truth.",
        "score2_description": "The response partially matches the ground truth but includes significant errors, omissions, or irrelevant information.",
        "score3_description": "The response generally aligns with the ground truth but may lack detail, clarity, or have minor inaccuracies.",
        "score4_description": "The response is mostly accurate and aligns well with the ground truth, with only minor issues or missing details.",
        "score5_description": "The response is fully accurate, aligns completely with the ground truth, and is clear and detailed.",
    },
    "Tone Rubric": {
        "score1_description": "The tone is rude, unprofessional, toxic, or extremely robotic and hard to understand.",
        "score2_description": "The tone is slightly inappropriate, overly harsh, too formal, or lacks empathy and clarity.",
        "score3_description": "The tone is neutral but flat, mechanical, and lacks friendliness or engagement.",
        "score4_description": "The tone is polite, clear, and helpful with moderate friendliness and professionalism.",
        "score5_description": "The tone is natural, friendly, empathetic, and highly professional with strong user engagement.",
    },
}

# Default rubric used by the "Rubrics score" metric when no preset has
# been chosen yet. Kept for backwards compatibility with code paths
# (e.g. CLI) that don't go through the Streamlit editor.
RUBRICS: dict[str, str] = dict(RUBRIC_PRESETS["Factual QA Rubric"])

# The rubric preset that is selected by default in the Config tab.
DEFAULT_RUBRIC_PRESET = "Factual QA Rubric"


def get_rubric_level_for_score(
    score: float,
    rubrics: dict[str, str] | None = None,
) -> tuple[int | None, str]:
    """Given a numeric Rubrics score, return (level, description) for the
    matching level in the given rubric mapping. Levels are 1-5. If the
    score is outside the 1-5 range, returns (None, "") so callers can no-op.

    IMPORTANT: callers should pass `get_active_rubrics()` so the
    description shown next to the score matches the rubric the user
    actually selected in the Config tab. Falling back to the module-level
    `RUBRICS` constant would always show the Factual QA description
    regardless of which preset is active.
    """
    try:
        level = int(round(float(score)))
    except (TypeError, ValueError):
        return None, ""
    key = f"score{level}_description"
    rubric_source = rubrics if rubrics is not None else RUBRICS
    if level < 1 or level > 5 or key not in rubric_source:
        return None, ""
    return level, rubric_source[key]


def get_active_rubrics() -> dict[str, str]:
    """Return the current rubric mapping for scoring.

    Prefers the user-edited version in `st.session_state["rubrics"]`
    (so rubric edits made in the Config tab take effect immediately).
    Falls back to the module-level `RUBRICS` constant.
    """
    edited = st.session_state.get("rubrics") if hasattr(st, "session_state") else None
    if edited and isinstance(edited, dict) and len(edited) == 5:
        return edited
    return dict(RUBRICS)


def get_rubric_preset(name: str) -> dict[str, str]:
    """Return the level descriptions for a rubric preset, or the default
    if the name is not recognized."""
    return dict(RUBRIC_PRESETS.get(name, RUBRIC_PRESETS[DEFAULT_RUBRIC_PRESET]))


def render_rubric_editor() -> dict[str, str]:
    """Render the editable rubric levels (1-5) in an expander.

    Returns the current rubric mapping from `st.session_state["rubrics"]`
    (or the default if the user has not edited it yet). The Config tab
    calls this BEFORE the form so changes propagate to the evaluation.
    """
    # Seed session state with the default rubric the first time the page loads.
    if "rubric_preset_name" not in st.session_state:
        st.session_state["rubric_preset_name"] = DEFAULT_RUBRIC_PRESET
    if "rubrics" not in st.session_state:
        st.session_state["rubrics"] = dict(RUBRIC_PRESETS[st.session_state["rubric_preset_name"]])

    # Highlight the "Rubrics score" metric as a always-on, configurable metric.
    st.markdown(
        (
            '<div style="display:flex; align-items:center; gap:10px; '
            'margin:4px 0 8px; padding:8px 12px; border:1px solid #fbbf24; '
            'border-radius:10px; background:rgba(251,191,36,0.06);">'
            '<div style="font-family:\'Orbitron\',\'Rajdhani\',\'Segoe UI\',system-ui,sans-serif; '
            'color:#fbbf24; letter-spacing:0.10em; text-transform:uppercase; '
            'font-size:0.78rem; font-weight:700;">Rubrics score</div>'
            '<div style="font-size:0.85rem; color:#e2e8f0; line-height:1.4;">'
            'Always-on 1-5 rating metric. Pick a rubric type below, then fine-tune '
            'the level descriptions — the judge LLM will use your wording when scoring.'
            '</div></div>'
        ),
        unsafe_allow_html=True,
    )

    with st.expander("Edit Rubric Levels (1 = worst, 5 = best)", expanded=False):
        st.caption(
            "These descriptions are sent to the judge LLM as the scoring rubric. "
            "Tune them to match what you consider a good vs. bad response."
        )

        # Rubric-type dropdown. Picking a preset overwrites the level
        # descriptions in session_state so the text areas below re-render
        # with the new wording (the user can still tweak any level after).
        preset_names = list(RUBRIC_PRESETS.keys())
        current_preset = st.session_state.get("rubric_preset_name", DEFAULT_RUBRIC_PRESET)
        if current_preset not in RUBRIC_PRESETS:
            current_preset = DEFAULT_RUBRIC_PRESET
        selected_preset = st.selectbox(
            "Rubric type",
            options=preset_names,
            index=preset_names.index(current_preset),
            help=(
                "Picking a preset loads its level descriptions into the editor. "
                "You can still edit any level afterward."
            ),
            key="rubric_preset_select",
        )
        if selected_preset != st.session_state.get("rubric_preset_name"):
            st.session_state["rubric_preset_name"] = selected_preset
            st.session_state["rubrics"] = dict(RUBRIC_PRESETS[selected_preset])
            st.rerun()

        # Two columns to keep the editor compact (5 text areas don't all fit in one row).
        # NOTE: the widget key includes the preset name on purpose — this is what
        # forces Streamlit to re-create the text areas with the new default values
        # when the user switches presets. Using a static key (e.g. "rubric_1")
        # would let Streamlit preserve the OLD text the user (or a prior preset)
        # typed, so the visible text would not match the selected dropdown.
        col_left, col_right = st.columns(2)
        for level in range(1, 6):
            key = f"score{level}_description"
            default_value = st.session_state["rubrics"].get(
                key, RUBRIC_PRESETS[st.session_state["rubric_preset_name"]].get(key, "")
            )
            target_column = col_left if level % 2 == 1 else col_right
            with target_column:
                widget_key = f"rubric_{st.session_state['rubric_preset_name']}_{level}"
                edited_value = st.text_area(
                    f"Level {level}",
                    value=default_value,
                    key=widget_key,
                    height=110,
                )
                st.session_state["rubrics"][key] = edited_value

        if st.button("Reset Rubric to Default", use_container_width=True):
            active_preset = st.session_state.get("rubric_preset_name", DEFAULT_RUBRIC_PRESET)
            st.session_state["rubrics"] = dict(RUBRIC_PRESETS[active_preset])
            st.rerun()

    return st.session_state["rubrics"]

# Recommended score ranges for each metric. The UI shows these in green/yellow/red
# so you can tell at a glance whether a score is healthy, borderline, or poor.
METRIC_RECOMMENDATIONS = {
    "Context relevance": {"min": 0.8, "max": 1.0, "label": "Recommended: 0.80-1.00"},
    "Context precision with reference": {"min": 0.8, "max": 1.0, "label": "Recommended: 0.80-1.00"},
    "Context recall": {"min": 0.8, "max": 1.0, "label": "Recommended: 0.80-1.00"},
    "Response groundedness": {"min": 0.8, "max": 1.0, "label": "Recommended: 0.80-1.00"},
    "Faithfulness": {"min": 0.85, "max": 1.0, "label": "Recommended: 0.85-1.00"},
    "Factual correctness": {"min": 0.7, "max": 1.0, "label": "Recommended: 0.70-1.00"},
    "Rubrics score": {"min": 4, "max": 5, "label": "Recommended: 4-5"},
}
METRIC_GUIDANCE = {
    "Context relevance": {
        "what": "Checks whether the retrieved contexts are relevant to the user query.",
        "inputs": "Query + Retrieved contexts",
        "how": "Formula: relevant retrieved contexts / total retrieved contexts",
        "meaning": "Low means retrieval is noisy or off-topic; high means the retrieved context closely matches the query.",
    },
    "Context precision with reference": {
        "what": "Checks how much of the retrieved context is actually useful for supporting the reference answer.",
        "inputs": "Query + Reference + Retrieved contexts",
        "how": "Formula: retrieved contexts that support the reference / total retrieved contexts",
        "meaning": "Low means too many extra chunks were retrieved; high means retrieval is focused and useful.",
    },
    "Context recall": {
        "what": "Checks whether the retrieved context contains the facts needed to cover the reference answer.",
        "inputs": "Query + Reference + Retrieved contexts",
        "how": "Formula: reference claims supported by retrieved contexts / total reference claims",
        "meaning": "Low means retrieval missed important facts; high means retrieval captured most or all needed information.",
    },
    "Response groundedness": {
        "what": "Checks whether the generated answer is supported by the retrieved context.",
        "inputs": "Response + Retrieved contexts",
        "how": "Formula: response claims supported by retrieved contexts / total response claims",
        "meaning": "Low means the answer includes unsupported content; high means the answer stays anchored in retrieved evidence.",
    },
    "Faithfulness": {
        "what": "Checks whether the answer's claims are consistent with the retrieved context.",
        "inputs": "Query + Response + Retrieved contexts",
        "how": "Formula: response claims consistent with retrieved contexts / total response claims",
        "meaning": "Low means hallucination or contradiction; high means the answer is context-consistent.",
    },
    "Factual correctness": {
        "what": "Checks whether the answer matches the provided ground-truth reference.",
        "inputs": "Response + Reference",
        "how": "Formula: response claims matching reference claims / total evaluated claims",
        "meaning": "Low means the answer misses or changes key facts from the reference; high means the answer is close to the expected truth.",
    },
    "Rubrics score": {
        "what": "Judges the response against a custom 1-5 rubric (defined in this app).",
        "inputs": "Query + Response + Reference",
        "how": "Formula: rubric level (1-5) chosen by the judge LLM based on the response vs. the reference",
        "meaning": "Low means the response is off-target or contains significant errors; high means the response is accurate, complete, and clear.",
    },
}


# Load secrets/settings from the 1.env file into environment variables
# (e.g. OPENAI_API_KEY, LLM_API_ENDPOINT, LLM_MODEL, etc.).
load_dotenv(ENV_FILE, override=True)


# ---------------------------------------------------------------------------
# A small compatibility shim: some RAGAS internals try to import
# "langchain_community.chat_models.vertexai" even when we never use Vertex AI.
# Importing that module can fail on machines without extra packages, which
# would crash our app. To avoid that, we create a tiny stub module before
# the real RAGAS import below, so the import never fails.
# ---------------------------------------------------------------------------
def ensure_vertexai_compatibility() -> None:
    if "langchain_community.chat_models.vertexai" in sys.modules:
        return  # already set up, nothing to do

    vertexai_module = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:
        pass  # empty placeholder class; we never actually use Vertex AI

    vertexai_module.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = vertexai_module


ensure_vertexai_compatibility()


# Now we can safely import RAGAS — these are the six metrics we support.
# "collections" = the new, simpler RAGAS metric API.
from ragas import SingleTurnSample
from ragas.llms import llm_factory
from ragas.metrics.collections import (
    ContextPrecisionWithReference,  # was retrieval focused + useful?
    ContextRecall,                  # did retrieval cover the answer?
    ContextRelevance,               # are the retrieved docs on-topic?
    Faithfulness,                   # is the answer consistent with the docs?
    FactualCorrectness,             # does the answer match the reference?
    ResponseGroundedness,           # is the answer supported by the docs?
    RubricsScoreWithReference,      # judge the response against a custom rubric
)


# ---------------------------------------------------------------------------
# Simple data records used across the app.
# A "@dataclass" is just a clean way to bundle a few fields together
# (it auto-generates __init__, __repr__, etc.).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EvaluationRow:
    """One question + reference answer pair from the test set."""
    question: str
    reference: str


@dataclass(frozen=True)
class AppConfig:
    """All the settings needed to run an evaluation. Built once from the UI form."""
    rag_endpoint: str          # URL of our RAG system (asked for the answer + docs)
    llm_api_key: str           # API key for the judge LLM
    llm_api_endpoint: str      # Base URL of the judge LLM (OpenAI-compatible)
    llm_model: str             # Model name of the judge LLM
    llm_temperature: float     # 0 = deterministic, higher = more creative
    llm_max_tokens: int        # Cap on how long the judge LLM's reply can be
    selected_metrics: list[str] # Which metrics the user picked in the dropdown
    rows: list[EvaluationRow]  # The questions/answers to evaluate


@dataclass(frozen=True)
class EvaluationResult:
    """The final output for one row: scores plus the input data we scored against."""
    row_number: int
    question: str
    response: str
    reference: str
    retrieved_contexts: list[str]
    scores: dict[str, float]   # metric name -> score (between 0 and 1)
    reasons: dict[str, str] = field(default_factory=dict)  # metric name -> judge LLM explanation


# ---------------------------------------------------------------------------
# Small helper utilities
# ---------------------------------------------------------------------------
def get_required_setting(name: str) -> str:
    """Read a required environment variable; raise a clear error if it's missing."""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def normalize_openai_base_url(endpoint: str) -> str:
    """Strip /chat/completions or /completions off the end of a URL if present,
    so it can be used as a base URL for the OpenAI client."""
    normalized_endpoint = endpoint.rstrip("/")
    for suffix in OPENAI_COMPLETION_SUFFIXES:
        if normalized_endpoint.endswith(suffix):
            return normalized_endpoint[: -len(suffix)]
    return normalized_endpoint


def normalize_response_content(response: Any) -> Any:
    for choice in getattr(response, "choices", []):
        message = getattr(choice, "message", None)
        if message is None:
            continue

        content = getattr(message, "content", None)
        reasoning_content = getattr(message, "reasoning_content", None)

        if not content and reasoning_content:
            content = reasoning_content.strip()

        if not content:
            continue

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            message.content = content
            continue

        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            message.content = json.dumps(parsed[0])
        elif isinstance(parsed, dict):
            message.content = json.dumps(parsed)
        else:
            message.content = content

    return response


def normalize_text(text: Any) -> str:
    """Clean up text for display/scoring:
       - decode HTML entities like &amp;
       - normalize line breaks (\\r\\n -> \\n)
       - collapse extra spaces and blank lines
       - strip leading/trailing whitespace
    """
    cleaned_text = html.unescape(str(text or ""))
    cleaned_text = cleaned_text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def patch_async_client_for_baseten(client: AsyncOpenAI) -> AsyncOpenAI:
    """Some LLM endpoints (notably Baseten) return a JSON-wrapped response
    inside the chat message content. This wrapper unwraps that JSON so the
    rest of the code can treat replies like normal text."""
    original_create = client.chat.completions.create

    async def create_with_normalized_content(*args, **kwargs):
        response = await original_create(*args, **kwargs)
        return normalize_response_content(response)

    client.chat.completions.create = create_with_normalized_content
    return client


def load_default_rows() -> list[EvaluationRow]:
    """Load the default test questions/references for the UI.

    Lookup order (first non-empty wins):
        1. `ARIA_DATA_FILE` env var (defaults to `testdata/ARIA_data.csv`).
        2. `testdata/Test5.json` (the original behaviour of this app).
        3. `QUESTION` / `REFERENCE_ANSWER` env vars.
    """
    aria_path = Path(os.getenv("ARIA_DATA_FILE", str(ARIA_DATA_FILE)))
    if aria_path.exists():
        rows = load_test_rows_from_csv(aria_path)
        if rows:
            return rows

    test_rows = [
        EvaluationRow(
            question=row.get("question", "").strip(),
            reference=normalize_text(row.get("reference", "")),
        )
        for row in load_test_data(TEST_DATA_FILE)
        if row.get("question") or row.get("reference")
    ]

    if test_rows:
        return test_rows

    return [
        EvaluationRow(
            question=os.getenv("QUESTION", "").strip(),
            reference=normalize_text(os.getenv("REFERENCE_ANSWER", "")),
        )
    ]


def load_test_rows_from_csv(path: Path) -> list[EvaluationRow]:
    """Load question/reference rows from a CSV file with a 'question' column.

    Any column named 'reference' becomes the ground truth. Other columns are
    ignored. Blank rows are skipped.
    """
    rows: list[EvaluationRow] = []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or "question" not in reader.fieldnames:
                return []
            for record in reader:
                question = str(record.get("question", "") or "").strip()
                reference = normalize_text(record.get("reference", ""))
                if not question:
                    continue
                rows.append(EvaluationRow(question=question, reference=reference))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    return rows


def build_default_config() -> AppConfig:
    """Build the starting AppConfig from environment variables and the test data file.
    The user can then tweak any of these values in the UI form."""
    return AppConfig(
        rag_endpoint=get_required_setting("RAG_ENDPOINT"),
        llm_api_key=get_required_setting("OPENAI_API_KEY"),
        llm_api_endpoint=get_required_setting("LLM_API_ENDPOINT"),
        llm_model=get_required_setting("LLM_MODEL"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "8192")),
        selected_metrics=AVAILABLE_METRICS.copy(),
        rows=load_default_rows(),
    )


def build_rows_dataframe(rows: list[EvaluationRow]) -> pd.DataFrame:
    """Turn the list of EvaluationRow into a pandas DataFrame so the UI
    can show it as an editable table."""
    return pd.DataFrame(
        [{"Question": row.question, "Ground Truth": row.reference} for row in rows]
    )


def parse_rows(dataframe: pd.DataFrame) -> list[EvaluationRow]:
    """Read the edited DataFrame back into EvaluationRow objects.
    Skips empty rows where both the question and ground truth are blank."""
    rows: list[EvaluationRow] = []
    for record in dataframe.to_dict(orient="records"):
        question = str(record.get("Question", "") or "").strip()
        reference = normalize_text(record.get("Ground Truth", ""))
        if not question and not reference:
            continue
        rows.append(EvaluationRow(question=question, reference=reference))
    return rows


def build_llm(config: AppConfig):
    """Build the 'judge' LLM that RAGAS will call to score answers.
    We use the official AsyncOpenAI client pointing at whatever
    OpenAI-compatible endpoint is configured in 1.env."""
    import httpx

    os.environ["OPENAI_API_KEY"] = config.llm_api_key

    # Configure httpx client with proper connection handling for Windows/Streamlit
    httpx_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            timeout=120.0,  # Total timeout
            connect=30.0,   # Connection timeout
            read=30.0,      # Read timeout
            write=30.0,     # Write timeout
            pool=30.0       # Pool timeout
        ),
        verify=False,  # Skip SSL verification for compatibility
        http2=False,   # Disable HTTP/2 for compatibility
        limits=httpx.Limits(
            max_connections=5,
            max_keepalive_connections=2,
        )
    )
    
    client = AsyncOpenAI(
        api_key=config.llm_api_key,
        base_url=normalize_openai_base_url(config.llm_api_endpoint),
        http_client=httpx_client,  # Use custom httpx client
    )
    client = patch_async_client_for_baseten(client)
    return llm_factory(
        config.llm_model,
        client=client,
        temperature=config.llm_temperature,
        max_tokens=config.llm_max_tokens,
    )


def build_sample(row: EvaluationRow) -> SingleTurnSample:
    """Ask the Aria RAG system the question and package the result into a
    RAGAS `SingleTurnSample` ready for scoring.

    Uses the same AriaClient as Test1_contextprecisionaria.py so token
    handling, streamed events, and source-page fetching stay in one place.
    The retrieved KB pages are HTML-stripped by AriaClient and capped at
    3000 chars per page (see MAX_SOURCE_CONTEXT_CHARS in Test1).

    We call the *sync* AriaClient.ask_with_sources (not the async wrapper)
    because Streamlit is already running an event loop, and trying to nest
    asyncio.run() / new_event_loop() inside it raises
    "Cannot run the event loop while another loop is running".
    """
    aria_config = _T1_CONFIG
    aria_client = AriaClient(aria_config)
    aria_response: AriaAnswerPayload = aria_client.ask_with_sources(
        row.question, aria_config.top_context_count
    )
    return SingleTurnSample(
        user_input=row.question,
        response=normalize_text(aria_response.answer),
        retrieved_contexts=[
            normalize_text(context)
            for context in aria_response.retrieved_contexts[:TOP_CONTEXT_COUNT]
            if normalize_text(context)
        ],
        reference=normalize_text(row.reference),
    )


def build_review_row(row_number: int, sample: SingleTurnSample) -> dict[str, Any]:
    """Convert a RAGAS sample into a plain dict the UI can show in edit boxes."""
    return {
        "row_number": row_number,
        "question": normalize_text(sample.user_input),
        "response": normalize_text(sample.response),
        "reference": normalize_text(sample.reference),
        "retrieved_contexts": [normalize_text(context) for context in sample.retrieved_contexts],
    }


def build_sample_from_review_row(review_row: dict[str, Any]) -> SingleTurnSample:
    """Inverse of build_review_row: take the (possibly edited) UI data and
    turn it back into a RAGAS sample ready for scoring."""
    return SingleTurnSample(
        user_input=normalize_text(review_row.get("question", "")),
        response=normalize_text(review_row.get("response", "")),
        retrieved_contexts=[
            normalize_text(context)
            for context in review_row.get("retrieved_contexts", [])
            if normalize_text(context)
        ],
        reference=normalize_text(review_row.get("reference", "")),
    )


def build_review_rows(config: AppConfig) -> list[dict[str, Any]]:
    """Step 1 driver: call the RAG system once per question and return the
    data so the user can review/edit it before scoring."""
    os.environ["RAG_ENDPOINT"] = config.rag_endpoint
    review_rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(config.rows, start=1):
        sample = build_sample(row)
        review_rows.append(build_review_row(row_number, sample))
    return review_rows


def seed_review_widget_state(review_rows: list[dict[str, Any]]) -> None:
    """Pre-populate Streamlit's session_state so the review text boxes
    start with the values we just fetched from the RAG system."""
    for review_row in review_rows:
        row_number = review_row["row_number"]
        st.session_state[f"review_question_{row_number}"] = review_row["question"]
        st.session_state[f"review_response_{row_number}"] = review_row["response"]
        st.session_state[f"review_reference_{row_number}"] = review_row["reference"]
        for context_index, context in enumerate(review_row["retrieved_contexts"], start=1):
            st.session_state[f"review_context_{row_number}_{context_index}"] = context


def collect_review_rows(review_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read whatever the user typed into the review text boxes and build
    an updated list of rows (skipping empty context boxes)."""
    updated_review_rows: list[dict[str, Any]] = []
    for review_row in review_rows:
        row_number = review_row["row_number"]
        updated_contexts: list[str] = []
        for context_index, context in enumerate(review_row["retrieved_contexts"], start=1):
            updated_context = normalize_text(
                st.session_state.get(f"review_context_{row_number}_{context_index}", context)
            )
            if updated_context:
                updated_contexts.append(updated_context)

        updated_review_rows.append(
            {
                "row_number": row_number,
                "question": normalize_text(
                    st.session_state.get(f"review_question_{row_number}", review_row["question"])
                ),
                "response": normalize_text(
                    st.session_state.get(f"review_response_{row_number}", review_row["response"])
                ),
                "reference": normalize_text(
                    st.session_state.get(f"review_reference_{row_number}", review_row["reference"])
                ),
                "retrieved_contexts": updated_contexts,
            }
        )

    return updated_review_rows


def build_metric_definitions(llm_wrapper, sample: SingleTurnSample):
    """Return a dictionary mapping each metric name to:
       (the metric object, the inputs it needs from the sample).
    This makes it easy to look up "how do I score this with metric X?"
    for any given sample."""
    return {
        "Faithfulness": (
            Faithfulness(llm=llm_wrapper),
            {
                "user_input": sample.user_input,
                "response": sample.response,
                "retrieved_contexts": sample.retrieved_contexts,
            },
        ),
        "Factual correctness": (
            FactualCorrectness(llm=llm_wrapper),
            {
                "response": sample.response,
                "reference": sample.reference,
            },
        ),
        "Context recall": (
            ContextRecall(llm=llm_wrapper),
            {
                "user_input": sample.user_input,
                "retrieved_contexts": sample.retrieved_contexts,
                "reference": sample.reference,
            },
        ),
        "Context precision with reference": (
            ContextPrecisionWithReference(llm=llm_wrapper),
            {
                "user_input": sample.user_input,
                "reference": sample.reference,
                "retrieved_contexts": sample.retrieved_contexts,
            },
        ),
        "Response groundedness": (
            ResponseGroundedness(llm=llm_wrapper),
            {
                "response": sample.response,
                "retrieved_contexts": sample.retrieved_contexts,
            },
        ),
        "Context relevance": (
            ContextRelevance(llm=llm_wrapper),
            {
                "user_input": sample.user_input,
                "retrieved_contexts": sample.retrieved_contexts,
            },
        ),
        "Rubrics score": (
            RubricsScoreWithReference(rubrics=get_active_rubrics(), llm=llm_wrapper),
            {
                "user_input": sample.user_input,
                "response": sample.response,
                "reference": sample.reference,
            },
        ),
    }


def normalize_selected_metrics(selected_metrics: list[str]) -> list[str]:
    """Ensure always-on metrics (e.g. Rubrics score) are always included
    and dedupe the list, preserving the canonical display order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for metric_name in get_metric_order(list(selected_metrics) + list(ALWAYS_SELECTED_METRICS)):
        if metric_name in seen:
            continue
        seen.add(metric_name)
        ordered.append(metric_name)
    return ordered


async def evaluate_row(
    llm_wrapper,
    row_number: int,
    row: EvaluationRow,
    selected_metrics: list[str],
) -> EvaluationResult:
    """Score one EvaluationRow by first fetching its RAG response (Step 1)
    and then running the selected metrics on it (Step 2)."""
    sample = build_sample(row)
    return await evaluate_sample(
        llm_wrapper=llm_wrapper,
        row_number=row_number,
        sample=sample,
        selected_metrics=selected_metrics,
    )


async def evaluate_sample(
    llm_wrapper,
    row_number: int,
    sample: SingleTurnSample,
    selected_metrics: list[str],
) -> EvaluationResult:
    """Score an already-built RAGAS sample with the selected metrics.
    For each metric, we try up to 3 times if the LLM endpoint has a
    temporary connection hiccup, and we back off between retries."""
    import asyncio

    metric_definitions = build_metric_definitions(llm_wrapper, sample)
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}

    for metric_name in selected_metrics:
        metric, metric_inputs = metric_definitions[metric_name]
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                result = await metric.ascore(**metric_inputs)
                scores[metric_name] = result.value
                # Capture the judge LLM's reasoning (used most prominently by
                # the Rubrics score metric, which produces a 1-5 rating plus
                # an explanation of why that level was chosen).
                reason_text = getattr(result, "reason", None)
                if reason_text:
                    reasons[metric_name] = str(reason_text)
                break
            except Exception as exc:
                last_error = exc
                error_str = str(exc).lower()

                # Check if it's a connection/timeout error
                if any(keyword in error_str for keyword in ['connection', 'timeout', 'winerror', 'socket', 'refused', 'reset']):
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[Metric: {metric_name}] Connection issue (attempt {attempt + 1}/{max_retries}): {exc}")
                        print(f"Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue

                # For non-connection errors, fail immediately
                raise RuntimeError(
                    f"{metric_name} failed. Increase LLM Max Tokens or shorten the ground truth/reference text. Original error: {exc}"
                ) from exc

        # If all retries failed with connection error
        if metric_name not in scores:
            raise RuntimeError(
                f"{metric_name} failed after {max_retries} retry attempts. Connection issue with LLM endpoint. Original error: {last_error}"
            ) from last_error

    return EvaluationResult(
        row_number=row_number,
        question=sample.user_input,
        response=sample.response,
        reference=sample.reference,
        retrieved_contexts=sample.retrieved_contexts,
        scores=scores,
        reasons=reasons,
    )


async def evaluate_metrics(config: AppConfig) -> list[EvaluationResult]:
    """Run the full evaluation: fetch RAG responses and score them with metrics.
    Returns a list of EvaluationResult objects, one per question."""
    os.environ["RAG_ENDPOINT"] = config.rag_endpoint
    llm_wrapper = build_llm(config)
    results: list[EvaluationResult] = []

    for row_number, row in enumerate(config.rows, start=1):
        results.append(
            await evaluate_row(
                llm_wrapper=llm_wrapper,
                row_number=row_number,
                row=row,
                selected_metrics=config.selected_metrics,
            )
        )

    return results


async def evaluate_review_rows(
    config: AppConfig, review_rows: list[dict[str, Any]]
) -> list[EvaluationResult]:
    """Step 2 driver: score the (already-reviewed) rows from the UI.
    We do NOT re-fetch from the RAG system here — the user has the
    final say on what data to score."""
    llm_wrapper = build_llm(config)
    results: list[EvaluationResult] = []
    for review_row in review_rows:
        sample = build_sample_from_review_row(review_row)
        results.append(
            await evaluate_sample(
                llm_wrapper=llm_wrapper,
                row_number=int(review_row["row_number"]),
                sample=sample,
                selected_metrics=config.selected_metrics,
            )
        )
    return results


def run_async(coroutine):
    """Run an async function from a synchronous context (like Streamlit's
    normal rerun loop). It works whether or not we're already inside an
    asyncio event loop, which can happen when Streamlit auto-reruns the script."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    # We're already inside a running loop, so build a new one to run our work.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def build_summary_rows(results: list[EvaluationResult]) -> list[dict[str, Any]]:
    """Turn a list of EvaluationResult into a flat list of dicts (one per row)
    suitable for displaying in a summary table."""
    summary_rows: list[dict[str, Any]] = []
    for result in results:
        row_summary: dict[str, Any] = {
            "Row": result.row_number,
            "Query": result.question,
            "Response": result.response,
            "Ground Truth": result.reference,
            "Contexts": len(result.retrieved_contexts),
        }
        for metric_name in get_metric_order(result.scores.keys()):
            row_summary[metric_name] = result.scores[metric_name]
        summary_rows.append(row_summary)
    return summary_rows


def get_metric_order(metric_names) -> list[str]:
    """Return the metrics in the canonical display order defined by METRIC_GROUPS.
    Only includes metrics that are actually present in the input."""
    metric_name_set = set(metric_names)
    ordered_metric_names: list[str] = []
    for _, grouped_metric_names in METRIC_GROUPS:
        ordered_metric_names.extend(
            [metric_name for metric_name in grouped_metric_names if metric_name in metric_name_set]
        )
    return ordered_metric_names


def get_active_metric_filter() -> set[str] | None:
    """Return the set of metric names the user actually selected for the
    most recent evaluation, or None if no evaluation has been run yet.

    The source of truth is the *live* multiselect widget in the Config
    tab (so newly added/removed metrics take effect immediately on the
    Results tab), with the stored `evaluation_config.selected_metrics`
    used as a fallback when the user hasn't opened the Config tab yet.

    Always-on metrics (Rubrics score) are merged in so they remain
    visible even if the user cleared the multiselect.
    """
    user_selected: list[str] | None = None
    if hasattr(st, "session_state"):
        user_selected = st.session_state.get("metrics_multiselect")
    if user_selected is None:
        config: AppConfig | None = st.session_state.get("evaluation_config")
        if config is None:
            return None
        return set(config.selected_metrics)
    return set(user_selected) | set(ALWAYS_SELECTED_METRICS)


def get_metric_recommendation(metric_name: str) -> dict[str, float | str]:
    """Return the recommended score range for a metric, with a sensible default
    of 0.8-1.0 if the metric isn't in our recommendations table."""
    return METRIC_RECOMMENDATIONS.get(
        metric_name,
        {"min": 0.8, "max": 1.0, "label": "Recommended: 0.80-1.00"},
    )


def get_metric_guidance(metric_name: str) -> dict[str, str]:
    """Return the human-readable explanation text for a metric.
    Used in the 'Metric' tab of the UI."""
    return METRIC_GUIDANCE.get(
        metric_name,
        {
            "what": "Checks the quality of this metric for the current RAG stage.",
            "inputs": "Metric-specific evaluation inputs",
            "how": "Formula: metric-supported units / total evaluated units",
            "meaning": "Low means weaker quality for this metric; high means stronger quality for this metric.",
        },
    )


def get_metric_stage(metric_name: str) -> str:
    """Look up which RAG stage (Retrieval / Augmentation / Generation) a metric belongs to."""
    for stage_name, grouped_metric_names in METRIC_GROUPS:
        if metric_name in grouped_metric_names:
            return stage_name
    return "Unknown"


def build_metric_guide_rows(metric_names: list[str]) -> list[dict[str, str]]:
    """Build the rows of the metric guide table shown in the 'Metric' tab."""
    guide_rows: list[dict[str, str]] = []
    for metric_name in metric_names:
        guidance = get_metric_guidance(metric_name)
        guide_rows.append(
            {
                "Metric": metric_name,
                "RAG Stage": get_metric_stage(metric_name),
                "Recommended Range": str(get_metric_recommendation(metric_name)["label"]).replace(
                    "Recommended: ", ""
                ),
                "What it is": guidance["what"],
                "Inputs": guidance["inputs"],
                "How it is calculated": guidance["how"],
                "Low vs High": guidance["meaning"],
            }
        )
    return guide_rows


def render_metric_guide(metric_names: list[str]) -> None:
    """Render the 'Metric Guide' table shown in the Metric tab.

    Cyberpunk-themed, 7-column grid table. Inline styles are used on the
    grid container and on every cell so the layout works even if the
    global <style> block from st.html(...) fails to reach the browser
    (Streamlit WebSocket re-connect issues can drop the theme).

    The caller (render_metric_tab) is responsible for the page-level
    'Metric Guide' subheader — we render the table itself, not a
    second copy of the heading.
    """
    inject_dashboard_styles()
    guide_rows = build_metric_guide_rows(metric_names)

    header_cells = [
        "Metric",
        "RAG Stage",
        "Recommended Range",
        "What it is",
        "Inputs",
        "Formula",
        "Low vs High",
    ]

    # Inline the grid layout so the table renders as a real 7-column grid
    # even if the global CSS injection is dropped by a stale browser tab.
    grid_template = (
        "minmax(180px, 0.9fr) minmax(160px, 0.75fr) minmax(150px, 0.75fr) "
        "minmax(320px, 1.15fr) minmax(240px, 0.9fr) minmax(360px, 1.2fr) "
        "minmax(340px, 1.15fr)"
    )

    # Cyberpunk-themed inline styles for the table (mirrors the .ragas-guide-*
    # CSS rules in inject_dashboard_styles, but applied directly so the
    # table still lays out correctly if the global theme didn't load).
    base_cell_style = (
        "padding:14px 16px; border-right:1px solid rgba(34,211,238,0.22); "
        "border-bottom:1px solid rgba(255,255,255,0.05); "
        "background:rgba(255,255,255,0.01); color:#e2e8f0; "
        "font-size:0.92rem; line-height:1.6; "
        "white-space:normal; word-break:break-word; min-height:108px; "
        "display:flex; align-items:flex-start;"
    )
    header_style = (
        "padding:14px 16px; border-right:1px solid rgba(34,211,238,0.22); "
        "border-bottom:1px solid rgba(168,85,247,0.45); "
        "background:rgba(34,211,238,0.05); color:#22d3ee; "
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:0.78rem; letter-spacing:0.08em; text-transform:uppercase; "
        "font-weight:700; display:flex; align-items:center;"
    )
    metric_style = (
        "color:#f8fafc; font-weight:700; "
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif;"
    )
    stage_style = (
        "color:#f0abfc; "
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "letter-spacing:0.08em; text-transform:uppercase; "
        "font-size:0.78rem; font-weight:700;"
    )
    range_style = (
        "color:#a3e635; "
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "letter-spacing:0.05em; font-weight:700;"
    )

    header_html = "".join(
        f'<div style="{header_style}">{html.escape(label)}</div>'
        for label in header_cells
    )

    row_cells: list[str] = []
    for row in guide_rows:
        row_cells.append(
            f'<div style="{base_cell_style} {metric_style}">{html.escape(row["Metric"])}</div>'
        )
        row_cells.append(
            f'<div style="{base_cell_style} {stage_style}">{html.escape(row["RAG Stage"])}</div>'
        )
        row_cells.append(
            f'<div style="{base_cell_style} {range_style}">{html.escape(row["Recommended Range"])}</div>'
        )
        for key in ("What it is", "Inputs", "How it is calculated", "Low vs High"):
            row_cells.append(
                f'<div style="{base_cell_style}">{html.escape(row[key])}</div>'
            )

    # Note: the grid uses inline display:grid + grid-template-columns so it
    # lays out correctly even if the global .ragas-guide-grid CSS rule was
    # dropped by a stale browser tab.
    st.markdown(
        (
            '<div style="'
            'border:1px solid rgba(34,211,238,0.22); border-radius:12px; '
            'background:rgba(10,14,28,0.78); overflow:hidden; margin-top:10px; '
            '">'
            '<div style="overflow-x:auto;">'
            f'<div style="display:grid; grid-template-columns:{grid_template}; min-width:2050px;">'
            + header_html
            + "".join(row_cells)
            + '</div></div></div>'
        ),
        unsafe_allow_html=True,
    )


def inject_dashboard_grid_columns(metric_names: list[str], column_track: str) -> None:
    """Kept for API compatibility — the cyberpunk card layout no longer
    needs a fixed column track. The argument is ignored."""
    return


def inject_dashboard_styles() -> None:
    """Inject the neon / cyberpunk theme.

    The theme is self-contained: it overrides Streamlit's main background,
    typography, buttons, tabs, and forms so the entire app feels like a
    sci-fi console. We use `st.html(...)` because Streamlit sanitizes
    `<style>` tags out of `st.markdown`. `st.html` renders raw HTML/`<style>`
    verbatim, which is what we need for a global theme override.
    """
    st.html(
        """
<style>
/* ----------------------------------------------------------------
   Neon / cyberpunk theme — variables, page chrome, and components
   ---------------------------------------------------------------- */
:root {
    --neon-cyan: #22d3ee;
    --neon-magenta: #f0abfc;
    --neon-violet: #a855f7;
    --neon-lime: #a3e635;
    --neon-amber: #fbbf24;
    --neon-red: #fb7185;
    --neon-grid: rgba(34, 211, 238, 0.10);
    --bg-deep: #05060f;
    --bg-panel: rgba(10, 14, 28, 0.78);
    --bg-panel-strong: rgba(8, 10, 22, 0.92);
    --line: rgba(34, 211, 238, 0.22);
    --line-strong: rgba(168, 85, 247, 0.45);
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --text-bright: #f8fafc;
    --mono: "JetBrains Mono", "Fira Code", "Cascadia Mono", ui-monospace, monospace;
    --display: "Orbitron", "Rajdhani", "Segoe UI", system-ui, sans-serif;
}

.stApp {
    background:
        radial-gradient(1200px 600px at 20% -10%, rgba(168, 85, 247, 0.18), transparent 60%),
        radial-gradient(1000px 500px at 100% 0%, rgba(34, 211, 238, 0.15), transparent 60%),
        linear-gradient(180deg, #04050b 0%, #06080f 100%);
    color: var(--text);
    font-family: var(--mono);
}

/* Subtle grid backdrop — pure CSS, no images */
.stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background-image:
        linear-gradient(var(--neon-grid) 1px, transparent 1px),
        linear-gradient(90deg, var(--neon-grid) 1px, transparent 1px);
    background-size: 48px 48px, 48px 48px;
    mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
    -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
}

h1, h2, h3, h4 {
    font-family: var(--display) !important;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-bright) !important;
}

h1 {
    text-shadow: 0 0 18px rgba(34, 211, 238, 0.45);
}

h3, h4 {
    color: var(--neon-cyan) !important;
    text-shadow: 0 0 8px rgba(34, 211, 238, 0.35);
}

.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-dim) !important;
    font-style: italic;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: transparent;
    border-bottom: 1px solid var(--line);
}
.stTabs [data-baseweb="tab"] {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--line);
    border-bottom: none;
    color: var(--text-dim);
    font-family: var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 10px 18px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(180deg, rgba(34, 211, 238, 0.18), rgba(168, 85, 247, 0.08)) !important;
    color: var(--neon-cyan) !important;
    border-color: var(--neon-cyan) !important;
    box-shadow: 0 -2px 14px rgba(34, 211, 238, 0.35) !important;
}

/* Inputs, text areas, and select boxes */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
[data-baseweb="select"] > div {
    background: var(--bg-panel) !important;
    border: 1px solid var(--line) !important;
    color: var(--text-bright) !important;
    font-family: var(--mono) !important;
    caret-color: var(--neon-cyan);
}
.stTextInput input:focus,
.stTextArea textarea:focus,
.stNumberInput input:focus,
[data-baseweb="select"] > div:focus-within {
    border-color: var(--neon-cyan) !important;
    box-shadow: 0 0 0 1px var(--neon-cyan), 0 0 14px rgba(34, 211, 238, 0.35) !important;
}

/* Labels above inputs */
.stTextInput label,
.stNumberInput label,
.stTextArea label,
.stMultiSelect label,
[data-testid="stWidgetLabel"] {
    color: var(--neon-cyan) !important;
    font-family: var(--display) !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-size: 0.78rem !important;
}

/* Primary buttons — match the actual <button> element inside the
   Streamlit BaseButton wrappers. The "button" selector on its own isn't
   enough because BaseButton renders the styled node above the <button>. */
.stButton button,
.stFormSubmitButton button,
button[data-testid="stBaseButton-primaryFormSubmit"],
button[data-testid="stBaseButton-secondaryFormSubmit"],
[data-testid="stBaseButton-primaryFormSubmit"] button,
[data-testid="stBaseButton-secondaryFormSubmit"] button {
    background: linear-gradient(180deg, rgba(34, 211, 238, 0.18), rgba(168, 85, 247, 0.18)) !important;
    border: 1px solid var(--neon-cyan) !important;
    color: var(--neon-cyan) !important;
    font-family: var(--display) !important;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    font-weight: 700 !important;
    padding: 0.55rem 1.1rem !important;
    border-radius: 8px !important;
    box-shadow:
        0 0 0 1px rgba(34, 211, 238, 0.25) inset,
        0 0 18px rgba(34, 211, 238, 0.30) !important;
    transition: transform 80ms ease, box-shadow 120ms ease;
}
.stButton button:hover,
.stFormSubmitButton button:hover,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover,
button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
    border-color: var(--neon-magenta) !important;
    color: var(--neon-magenta) !important;
    box-shadow:
        0 0 0 1px rgba(240, 171, 252, 0.30) inset,
        0 0 22px rgba(240, 171, 252, 0.45) !important;
    transform: translateY(-1px);
}

/* Data editor (the rows table in Config) */
[data-testid="stDataEditor"] {
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
    background: var(--bg-panel);
}

/* Expanders */
.streamlit-expanderHeader,
[data-testid="stExpander"] details summary {
    background: linear-gradient(180deg, rgba(34, 211, 238, 0.08), transparent) !important;
    border: 1px solid var(--line) !important;
    border-radius: 10px !important;
    color: var(--text-bright) !important;
    font-family: var(--display) !important;
    letter-spacing: 0.04em;
    padding: 10px 14px !important;
}
[data-testid="stExpander"] details summary:hover {
    border-color: var(--neon-cyan) !important;
    box-shadow: 0 0 18px rgba(34, 211, 238, 0.25);
}
[data-testid="stExpander"] details {
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--bg-panel);
}

/* DataFrames (the Results summary table) */
.stDataFrame {
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
}

/* Info / success / error banners */
.stAlert {
    background: var(--bg-panel) !important;
    border: 1px solid var(--line) !important;
    color: var(--text-bright) !important;
}

/* ----------------------------------------------------------------
   Per-row score cards (used by render_score_cards)
   - All cards in a row are equal height and align their values
     on a shared baseline.
   - Score number is green if it meets the recommended minimum,
     yellow if it does not.
   ---------------------------------------------------------------- */
.ragas-score-row {
    display: flex;
    gap: 12px;
    align-items: stretch;
    margin: 8px 0 4px;
}
.ragas-score-card {
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    background: var(--bg-panel-strong);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 12px 14px 10px;
    text-align: center;
    min-height: 96px;
}
.ragas-score-card .ragas-score-name {
    font-family: var(--display);
    font-size: 0.66rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-dim);
    line-height: 1.25;
    /* Cap the label to 2 lines so a long name can't push the value down */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.5em;
}
.ragas-score-card .ragas-score-value {
    font-family: var(--display);
    font-size: 1.55rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    /* Fixed line-height so the number sits on the same baseline in every card */
    line-height: 1.1;
    margin: 6px 0 4px;
}
.ragas-score-card .ragas-score-range {
    margin: 0;
    font-size: 0.68rem;
    color: var(--text-dim);
    font-family: var(--mono);
    line-height: 1.3;
}

/* Green (at or above recommended minimum) */
.ragas-score-card.ragas-score-good {
    border-color: var(--neon-lime);
    box-shadow: inset 0 0 0 1px rgba(163, 230, 53, 0.25);
}
.ragas-score-card.ragas-score-good .ragas-score-value {
    color: var(--neon-lime);
    text-shadow: 0 0 10px rgba(163, 230, 53, 0.55);
}

/* Yellow (below recommended minimum) */
.ragas-score-card.ragas-score-low {
    border-color: var(--neon-amber);
    box-shadow: inset 0 0 0 1px rgba(251, 191, 36, 0.35);
}
.ragas-score-card.ragas-score-low .ragas-score-value {
    color: #fde68a;
    text-shadow: 0 0 10px rgba(251, 191, 36, 0.55);
}

/* ----------------------------------------------------------------
   Cyberpunk results dashboard (cards)
   ---------------------------------------------------------------- */
.ragas-dashboard {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-top: 6px;
}

.ragas-card {
    position: relative;
    background: var(--bg-panel-strong);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 18px 20px 16px;
    overflow: hidden;
    isolation: isolate;
}
.ragas-card::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg, rgba(34, 211, 238, 0.08), transparent 35%, rgba(168, 85, 247, 0.08) 100%);
    pointer-events: none;
    z-index: -1;
}
.ragas-card::after {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    width: 4px;
    height: 100%;
    background: linear-gradient(180deg, var(--neon-cyan), var(--neon-violet));
    box-shadow: 0 0 14px var(--neon-cyan);
}

.ragas-card-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
    border-bottom: 1px solid var(--line);
    padding-bottom: 10px;
    margin-bottom: 14px;
}

.ragas-card-index {
    font-family: var(--display);
    color: var(--neon-cyan);
    letter-spacing: 0.18em;
    font-size: 0.78rem;
}

.ragas-card-question {
    flex: 1;
    color: var(--text-bright);
    font-weight: 600;
    font-size: 1.02rem;
    line-height: 1.4;
}

.ragas-card-context-badge {
    font-family: var(--display);
    font-size: 0.7rem;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: var(--neon-magenta);
    border: 1px solid var(--neon-magenta);
    border-radius: 999px;
    padding: 4px 10px;
    box-shadow: 0 0 10px rgba(240, 171, 252, 0.25);
    white-space: nowrap;
}

.ragas-card-body {
    display: grid;
    grid-template-columns: minmax(260px, 1.1fr) minmax(260px, 1.1fr) minmax(320px, 1.4fr);
    gap: 18px;
}
@media (max-width: 1100px) {
    .ragas-card-body { grid-template-columns: 1fr; }
}

.ragas-card-section-label {
    font-family: var(--display);
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--neon-cyan);
    margin-bottom: 6px;
}

.ragas-card-text {
    color: var(--text);
    line-height: 1.55;
    font-size: 0.92rem;
    max-height: 200px;
    overflow-y: auto;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.04);
    border-radius: 8px;
}

.ragas-card-text::-webkit-scrollbar { width: 8px; }
.ragas-card-text::-webkit-scrollbar-thumb {
    background: var(--neon-cyan);
    border-radius: 999px;
}

.ragas-chip-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 10px;
}

.ragas-chip {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: rgba(8, 10, 22, 0.7);
}

.ragas-chip-name {
    font-family: var(--display);
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-dim);
}

.ragas-chip-score {
    font-family: var(--display);
    font-size: 1.4rem;
    font-weight: 700;
    letter-spacing: 0.04em;
}

.ragas-chip-range {
    font-size: 0.68rem;
    color: var(--text-dim);
    font-family: var(--mono);
}

.ragas-chip-good {
    border-color: var(--neon-lime);
    box-shadow: 0 0 14px rgba(163, 230, 53, 0.25);
}
.ragas-chip-good .ragas-chip-score { color: var(--neon-lime); text-shadow: 0 0 10px rgba(163, 230, 53, 0.55); }

.ragas-chip-medium {
    border-color: var(--neon-amber);
    box-shadow: 0 0 14px rgba(251, 191, 36, 0.25);
}
.ragas-chip-medium .ragas-chip-score { color: var(--neon-amber); text-shadow: 0 0 10px rgba(251, 191, 36, 0.55); }

.ragas-chip-low {
    border-color: var(--neon-amber);
    box-shadow: 0 0 14px rgba(251, 191, 36, 0.25);
}
.ragas-chip-low .ragas-chip-score { color: var(--neon-amber); text-shadow: 0 0 10px rgba(251, 191, 36, 0.55); }

.ragas-rubric-box {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid var(--neon-amber);
    background: rgba(251, 191, 36, 0.06);
    color: var(--text);
    font-size: 0.85rem;
    line-height: 1.5;
}
.ragas-rubric-level {
    font-family: var(--display);
    color: var(--neon-amber);
    letter-spacing: 0.10em;
    text-transform: uppercase;
    font-size: 0.72rem;
    margin-bottom: 4px;
}

/* Legacy / contextual helpers */
.ragas-context-item {
    margin-bottom: 10px;
    padding-bottom: 10px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.ragas-context-item:last-child {
    margin-bottom: 0;
    padding-bottom: 0;
    border-bottom: none;
}
.ragas-context-label {
    display: inline-block;
    margin-bottom: 6px;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(34, 211, 238, 0.10);
    color: var(--neon-cyan);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

/* ----------------------------------------------------------------
   Cyberpunk metric guide table
   ---------------------------------------------------------------- */
.ragas-guide-table {
    border: 1px solid var(--line);
    border-radius: 12px;
    background: var(--bg-panel);
    overflow: hidden;
    margin-top: 10px;
}
.ragas-guide-scroll { overflow-x: auto; }
.ragas-guide-grid {
    display: grid;
    grid-template-columns:
        minmax(180px, 0.9fr) minmax(160px, 0.75fr) minmax(150px, 0.75fr)
        minmax(320px, 1.15fr) minmax(240px, 0.9fr) minmax(360px, 1.2fr) minmax(340px, 1.15fr);
    min-width: 2050px;
}
.ragas-guide-header {
    padding: 14px 16px;
    border-right: 1px solid var(--line);
    border-bottom: 1px solid var(--line-strong);
    background: rgba(34, 211, 238, 0.05);
    color: var(--neon-cyan);
    font-family: var(--display);
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.ragas-guide-cell {
    min-height: 108px;
    padding: 16px;
    border-right: 1px solid rgba(255, 255, 255, 0.05);
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    background: rgba(255, 255, 255, 0.01);
    color: var(--text);
    font-size: 0.92rem;
    line-height: 1.6;
    white-space: normal;
    word-break: break-word;
}
.ragas-guide-cell-metric { color: var(--text-bright); font-weight: 700; }
.ragas-guide-cell-stage {
    color: var(--neon-magenta);
    font-family: var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-size: 0.78rem;
    font-weight: 700;
}
.ragas-guide-cell-range {
    color: var(--neon-lime);
    font-family: var(--display);
    letter-spacing: 0.05em;
    font-weight: 700;
}

/* Legacy helper classes used by per-row score cards */
.ragas-stage-label {
    margin: 18px 0 10px;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: var(--neon-cyan);
    font-family: var(--display);
}
.ragas-score-range {
    margin-top: 6px;
    font-size: 0.72rem;
    color: var(--text-dim);
    font-family: var(--mono);
}

/* Per-row rubric explanation (emitted by render_score_cards under the
   Rubrics card). Visually matches the chip-grid's .ragas-rubric-box. */
.ragas-rubric-explanation {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid var(--neon-amber);
    background: rgba(251, 191, 36, 0.06);
    color: var(--text);
    font-size: 0.85rem;
    line-height: 1.5;
}
.ragas-rubric-explanation .ragas-rubric-level {
    font-family: var(--display);
    color: var(--neon-amber);
    letter-spacing: 0.10em;
    text-transform: uppercase;
    font-size: 0.72rem;
    margin-bottom: 4px;
}
.ragas-rubric-explanation .ragas-rubric-text {
    color: var(--text);
}
</style>
        """
    )


def format_score_class(metric_name: str, score: float) -> str:
    """Decide which color a score pill/card should use.

    The user-requested colour scheme is:
      - green ('good')   if the score meets the recommended minimum
      - yellow ('low')   if the score is below the recommended minimum

    The "ragas-score-low" class name is kept for backwards compatibility
    but the CSS now paints it yellow (not red).
    """
    recommendation = get_metric_recommendation(metric_name)
    recommended_min = float(recommendation["min"])
    if score >= recommended_min:
        return "ragas-score-good"
    return "ragas-score-low"


def render_dashboard_table(results: list[EvaluationResult]) -> None:
    """Cyberpunk card-per-row dashboard.

    Each `EvaluationResult` becomes a self-contained card with:
      - a left neon accent bar
      - the question as the card header (with the row index + a context count badge)
      - a three-column body: Response | Reference | Retrieved Contexts
      - a chip grid showing one chip per metric, color-coded green/amber/red
        against the recommended range
      - an inline Rubrics explanation box for the Rubrics score metric

    Inline styles are used on every container / text / chip so the
    layout still works if the global <style> block from
    `inject_dashboard_styles()` fails to reach the browser (Streamlit
    WebSocket re-connect issues can drop the theme on a stale tab).
    The CSS rules in inject_dashboard_styles() are still emitted so the
    page chrome and unrelated elements continue to look cyberpunk.
    """
    inject_dashboard_styles()
    # Show only the metrics the user actually selected for this run
    # (plus always-on ones like Rubrics score). Otherwise the chips
    # display every metric that was ever scored, even if the user later
    # narrowed the selection in the Config tab.
    active_filter = get_active_metric_filter()
    if active_filter is not None and results:
        scored = set(results[0].scores.keys())
        visible_metrics = scored & active_filter
    else:
        visible_metrics = set(results[0].scores.keys()) if results else set()
    metric_names = get_metric_order(visible_metrics)

    # Shared inline style fragments (used in f-strings below)
    _dash_root = (
        "display:flex; flex-direction:column; gap:16px; margin-top:6px;"
    )
    _card_root = (
        "position:relative; background:rgba(8,10,22,0.92); "
        "border:1px solid rgba(34,211,238,0.22); border-radius:14px; "
        "padding:18px 20px 16px; overflow:hidden; isolation:isolate;"
    )
    _card_accent = (
        "background:linear-gradient(120deg, rgba(34,211,238,0.08), transparent 35%, "
        "rgba(168,85,247,0.08) 100%);"
    )
    _card_left_bar = (
        "background:linear-gradient(180deg, #22d3ee, #a855f7); "
        "box-shadow:0 0 14px #22d3ee;"
    )
    _card_header = (
        "display:flex; align-items:baseline; justify-content:space-between; "
        "gap:16px; border-bottom:1px solid rgba(34,211,238,0.22); "
        "padding-bottom:10px; margin-bottom:14px;"
    )
    _card_index = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "color:#22d3ee; letter-spacing:0.18em; font-size:0.78rem; "
        "white-space:nowrap;"
    )
    _card_question = (
        "flex:1; color:#f8fafc; font-weight:600; font-size:1.02rem; "
        "line-height:1.4;"
    )
    _card_badge = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:0.7rem; letter-spacing:0.10em; text-transform:uppercase; "
        "color:#f0abfc; border:1px solid #f0abfc; border-radius:999px; "
        "padding:4px 10px; box-shadow:0 0 10px rgba(240,171,252,0.25); "
        "white-space:nowrap;"
    )
    _card_body = (
        "display:grid; "
        "grid-template-columns:minmax(260px,1.1fr) minmax(260px,1.1fr) minmax(320px,1.4fr); "
        "gap:18px;"
    )
    _section_label = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:0.7rem; letter-spacing:0.12em; text-transform:uppercase; "
        "color:#22d3ee; margin-bottom:6px;"
    )
    _card_text = (
        "color:#e2e8f0; line-height:1.55; font-size:0.92rem; "
        "max-height:200px; overflow-y:auto; padding:10px 12px; "
        "background:rgba(255,255,255,0.02); "
        "border:1px solid rgba(255,255,255,0.04); border-radius:8px;"
    )
    _chip_grid = (
        "display:grid; "
        "grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; "
        "margin-top:16px;"
    )
    _chip_base = (
        "position:relative; display:flex; flex-direction:column; "
        "gap:6px; padding:10px 12px; border:1px solid rgba(34,211,238,0.22); "
        "border-radius:10px; background:rgba(8,10,22,0.7);"
    )
    _chip_good = (
        "border-color:#a3e635; box-shadow:0 0 14px rgba(163,230,53,0.25);"
    )
    _chip_low = (
        "border-color:#fbbf24; box-shadow:0 0 14px rgba(251,191,36,0.25);"
    )
    _chip_name = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:0.7rem; letter-spacing:0.08em; text-transform:uppercase; "
        "color:#94a3b8;"
    )
    _chip_score_good = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:1.4rem; font-weight:700; letter-spacing:0.04em; "
        "color:#a3e635; text-shadow:0 0 10px rgba(163,230,53,0.55);"
    )
    _chip_score_low = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:1.4rem; font-weight:700; letter-spacing:0.04em; "
        "color:#fbbf24; text-shadow:0 0 10px rgba(251,191,36,0.55);"
    )
    _chip_range = (
        "font-size:0.68rem; color:#94a3b8; "
        "font-family:'JetBrains Mono','Fira Code',ui-monospace,monospace;"
    )
    _context_item = (
        "margin-bottom:10px; padding-bottom:10px; "
        "border-bottom:1px solid rgba(255,255,255,0.05);"
    )
    _context_item_last = (
        "margin-bottom:0; padding-bottom:0; border-bottom:none;"
    )
    _context_label = (
        "display:inline-block; margin-bottom:6px; padding:2px 8px; "
        "border-radius:999px; background:rgba(34,211,238,0.10); "
        "color:#22d3ee; font-size:0.72rem; font-weight:700; "
        "letter-spacing:0.04em; text-transform:uppercase;"
    )
    _rubric_box = (
        "grid-column:1 / -1; margin-top:10px; padding:10px 12px; "
        "border-radius:10px; border:1px solid #fbbf24; "
        "background:rgba(251,191,36,0.06); color:#e2e8f0; "
        "font-size:0.85rem; line-height:1.5;"
    )
    _rubric_level = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "color:#fbbf24; letter-spacing:0.10em; text-transform:uppercase; "
        "font-size:0.72rem; margin-bottom:4px;"
    )

    cards_html: list[str] = []
    for result in results:
        # Response / Reference / Contexts panels (truncated via max-height on
        # the inline style). We inline the context item + label styles too so
        # they look right even if the global CSS didn't reach the page.
        context_items: list[str] = []
        total_contexts = len(result.retrieved_contexts)
        for context_index, context in enumerate(result.retrieved_contexts, start=1):
            item_style = _context_item if context_index < total_contexts else _context_item_last
            context_items.append(
                f'<div style="{item_style}">'
                f'<div style="{_context_label}">Context {context_index}</div>'
                f'<div>{html.escape(context)}</div>'
                f'</div>'
            )
        if not context_items:
            context_html = f'<div style="{_context_item}"><div>No contexts returned.</div></div>'
        else:
            context_html = "".join(context_items)

        # One chip per metric, color-coded green (>= recommended min) or
        # amber (< recommended min). All styles are inlined so the chip
        # looks right regardless of the global theme state.
        chip_cells: list[str] = []
        for metric_name in metric_names:
            score = float(result.scores[metric_name])
            color_class = format_score_class(metric_name, score)  # ragas-score-good | ragas-score-low
            is_good = color_class == "ragas-score-good"
            chip_box_style = _chip_base + (" " + _chip_good if is_good else " " + _chip_low)
            chip_score_style = _chip_score_good if is_good else _chip_score_low
            chip_cells.append(
                f'<div style="{chip_box_style}">'
                f'<div style="{_chip_name}">{html.escape(metric_name)}</div>'
                f'<div style="{chip_score_style}">{score:.4f}</div>'
                f'<div style="{_chip_range}">{html.escape(str(get_metric_recommendation(metric_name)["label"]))}</div>'
                f'</div>'
            )

            # Rubrics explanation: full-width box directly under the Rubrics chip.
            # Use the ACTIVE rubric (preset or user-edited) so the description
            # matches the wording shown in the Config tab's editor.
            if metric_name == "Rubrics score":
                active_rubric = get_active_rubrics()
                rubric_level, rubric_description = get_rubric_level_for_score(
                    score, active_rubric
                )
                if rubric_level is not None:
                    preset_label = st.session_state.get(
                        "rubric_preset_name", DEFAULT_RUBRIC_PRESET
                    )
                    chip_cells.append(
                        f'<div style="{_rubric_box}">'
                        f'<div style="{_rubric_level}">'
                        f'Level {rubric_level} &middot; {html.escape(preset_label)}</div>'
                        f'<div>{html.escape(rubric_description)}</div>'
                        f'</div>'
                    )

        cards_html.append(
            (
                # Outer card + accent gradient (relative, isolation:isolate so
                # the accent can sit behind the content via z-index:-1)
                f'<div style="{_card_root}">'
                # ::before equivalent — the soft cyan→violet wash behind the card
                f'<div aria-hidden="true" style="position:absolute; inset:0; pointer-events:none; z-index:-1; {_card_accent}"></div>'
                # ::after equivalent — the left neon accent bar
                f'<div aria-hidden="true" style="position:absolute; top:0; left:0; width:4px; height:100%; {_card_left_bar}"></div>'
                f'<div style="{_card_header}">'
                f'<div style="{_card_index}">ROW&nbsp;//&nbsp;{result.row_number:02d}</div>'
                f'<div style="{_card_question}">{html.escape(result.question)}</div>'
                f'<div style="{_card_badge}">{len(result.retrieved_contexts)} context(s)</div>'
                f'</div>'
                f'<div style="{_card_body}">'
                f'<div>'
                f'<div style="{_section_label}">Response</div>'
                f'<div style="{_card_text}">{html.escape(result.response)}</div>'
                f'</div>'
                f'<div>'
                f'<div style="{_section_label}">Reference</div>'
                f'<div style="{_card_text}">{html.escape(result.reference)}</div>'
                f'</div>'
                f'<div>'
                f'<div style="{_section_label}">Retrieved Contexts</div>'
                f'<div style="{_card_text}">{context_html}</div>'
                f'</div>'
                f'</div>'
                f'<div style="{_chip_grid}">'
                + "".join(chip_cells)
                + '</div>'
                f'</div>'
            )
        )

    st.markdown(
        f'<div style="{_dash_root}">' + "".join(cards_html) + '</div>',
        unsafe_allow_html=True,
    )


def render_results_tab() -> None:
    """Render the 'Results' tab: dashboard cards, summary table, and per-row details.
    If no evaluation has been run yet, just show a helpful message."""
    st.subheader("Evaluation Results")
    results: list[EvaluationResult] = st.session_state.get("evaluation_results", [])

    if not results:
        st.info("Run an evaluation from the Config tab to see results here.")
        return

    # If the user changed the metric multiselect since the last run, the
    # new metrics won't be in `results.scores` until they re-run Step 2.
    # Surface that explicitly so the chip-filtering looks intentional and
    # the user knows what to do.
    active_filter = get_active_metric_filter()
    if active_filter and results:
        scored = set(results[0].scores.keys())
        missing = active_filter - scored - set(ALWAYS_SELECTED_METRICS)
        if missing:
            st.warning(
                f"**{len(missing)} metric(s) selected but not yet scored**: "
                f"{', '.join(sorted(missing))}. Re-run **Step 2: Run Metrics** "
                "in the Config tab to score them."
            )

    st.markdown("### Dashboard View")
    render_dashboard_table(results)

    st.markdown("### Summary Table")
    st.dataframe(build_summary_rows(results), use_container_width=True, hide_index=True)

    st.markdown("### Row Details")
    for result in results:
        with st.expander(f"Row {result.row_number}: {result.question}", expanded=False):
            render_score_cards(result.scores, result.reasons)

            # Surface the judge LLM's reasoning for the Rubrics score, since
            # a 1-5 number is hard to interpret without the explanation.
            rubric_reason = (result.reasons or {}).get("Rubrics score")
            if rubric_reason:
                st.markdown("#### Rubrics score - Judge reasoning")
                st.info(rubric_reason)

            st.markdown("#### Query")
            st.write(result.question)

            st.markdown("#### Response")
            st.write(result.response)

            st.markdown("#### Ground Truth")
            st.write(result.reference)

            st.markdown(f"#### Retrieved Contexts ({len(result.retrieved_contexts)})")
            for context_index, context in enumerate(result.retrieved_contexts, start=1):
                with st.expander(f"Context {context_index}", expanded=False):
                    st.write(context)


def render_metric_tab() -> None:
    """Render the 'Metric' tab: a guide explaining every metric the user
    might see scores for. Uses the metrics from the latest run if any,
    otherwise the full list of available metrics."""
    st.subheader("Metric Guide")
    results: list[EvaluationResult] = st.session_state.get("evaluation_results", [])

    if results:
        metric_names = get_metric_order(results[0].scores.keys())
    else:
        metric_names = AVAILABLE_METRICS.copy()

    st.caption("Use this tab to understand what each metric measures, how it is judged, and what low or high scores mean.")
    render_metric_guide(metric_names)


# ---------------------------------------------------------------------------
# Analytics tab — chart-based overview of the current (or a saved) run
# ---------------------------------------------------------------------------
def _filter_results_to_active_metrics(
    results: list[EvaluationResult],
) -> list[EvaluationResult]:
    """Apply the live multiselect filter to a results list. Returns a
    shallow copy with each result's `scores` dict pruned to only the
    metrics the user currently has selected (plus always-on ones)."""
    active_filter = get_active_metric_filter()
    if active_filter is None:
        return results
    filtered: list[EvaluationResult] = []
    for result in results:
        pruned_scores = {
            metric_name: score
            for metric_name, score in result.scores.items()
            if metric_name in active_filter
        }
        # Reuse the same EvaluationResult dataclass via replace-like copy.
        filtered.append(
            EvaluationResult(
                row_number=result.row_number,
                question=result.question,
                response=result.response,
                reference=result.reference,
                retrieved_contexts=result.retrieved_contexts,
                scores=pruned_scores,
                reasons=result.reasons,
            )
        )
    return filtered


def _build_results_dataframe(
    results: list[EvaluationResult],
    metric_names: list[str],
) -> pd.DataFrame:
    """Flatten (row × metric) into a long-format DataFrame for Plotly."""
    rows: list[dict[str, Any]] = []
    for result in results:
        for metric_name in metric_names:
            score = result.scores.get(metric_name)
            if score is None:
                continue
            rows.append(
                {
                    "Row": f"Row {result.row_number}",
                    "Question": result.question,
                    "Metric": metric_name,
                    "Score": float(score),
                }
            )
    return pd.DataFrame(rows)


def _metric_color(score: float, recommended_min: float) -> str:
    """Color hex for a single score against its recommended minimum."""
    if score >= recommended_min:
        return "#a3e635"  # neon-lime
    return "#fbbf24"  # neon-amber


def _build_avg_bar_chart(
    results: list[EvaluationResult],
    metric_names: list[str],
) -> "go.Figure":
    """Bar chart: one bar per metric, showing the mean score across rows.
    Bars are colored green/amber against the recommended minimum."""
    averages: list[dict[str, Any]] = []
    for metric_name in metric_names:
        scores = [
            float(r.scores[metric_name])
            for r in results
            if r.scores.get(metric_name) is not None
        ]
        if not scores:
            continue
        mean_score = sum(scores) / len(scores)
        recommendation = get_metric_recommendation(metric_name)
        recommended_min = float(recommendation["min"])
        averages.append(
            {
                "Metric": metric_name,
                "Mean Score": mean_score,
                "Recommended Min": recommended_min,
                "Color": _metric_color(mean_score, recommended_min),
            }
        )

    fig = go.Figure()
    if not averages:
        fig.add_annotation(
            text="No metrics to chart yet.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    df = pd.DataFrame(averages)
    fig.add_trace(
        go.Bar(
            x=df["Metric"],
            y=df["Mean Score"],
            marker_color=df["Color"],
            text=[f"{v:.3f}" for v in df["Mean Score"]],
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Mean: %{y:.4f}<br>"
                "Recommended min: %{customdata}<extra></extra>"
            ),
            customdata=df["Recommended Min"].tolist(),
        )
    )
    # Add a horizontal line per metric at its recommended minimum.
    for _, row in df.iterrows():
        fig.add_hline(
            y=row["Recommended Min"],
            line=dict(color="#22d3ee", width=1, dash="dot"),
            opacity=0.5,
            annotation_text=f"min {row['Metric'][:8]}…",
            annotation_position="right",
            annotation_font_size=9,
            annotation_font_color="#22d3ee",
        )
    fig.update_layout(
        title="Average Score per Metric (across all rows)",
        xaxis_title="Metric",
        yaxis_title="Mean Score",
        yaxis=dict(range=[0, 1.05]),
        template="plotly_dark",
        height=420,
        margin=dict(t=60, l=50, r=30, b=80),
        showlegend=False,
    )
    return fig


def _build_heatmap(
    results: list[EvaluationResult],
    metric_names: list[str],
) -> "go.Figure":
    """Rows × metrics heatmap. Each cell is colored by its score; missing
    scores are shown as a blank cell with annotation."""
    if not results:
        fig = go.Figure()
        fig.add_annotation(text="No rows to chart.", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False)
        return fig

    row_labels = [f"Row {r.row_number}" for r in results]
    z_matrix: list[list[float | None]] = []
    text_matrix: list[list[str]] = []
    for result in results:
        z_row: list[float | None] = []
        t_row: list[str] = []
        for metric_name in metric_names:
            score = result.scores.get(metric_name)
            if score is None:
                z_row.append(None)
                t_row.append("—")
            else:
                z_row.append(float(score))
                t_row.append(f"{float(score):.3f}")
        z_matrix.append(z_row)
        text_matrix.append(t_row)

    fig = go.Figure(
        data=go.Heatmap(
            z=z_matrix,
            x=metric_names,
            y=row_labels,
            text=text_matrix,
            texttemplate="%{text}",
            textfont={"size": 11, "color": "#0a0e1c"},
            colorscale=[
                [0.0, "#fbbf24"],   # amber for low
                [0.79, "#fbbf24"],
                [0.80, "#a3e635"],  # green at the recommended threshold
                [1.0, "#22d3ee"],   # cyan for very high
            ],
            zmin=0,
            zmax=1,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Metric: %{x}<br>"
                "Score: %{z:.4f}<extra></extra>"
            ),
            xgap=2,
            ygap=2,
        )
    )
    fig.update_layout(
        title="Per-Row × Per-Metric Score Heatmap",
        xaxis_title="Metric",
        yaxis_title="Row",
        template="plotly_dark",
        height=max(280, 80 * len(results) + 120),
        margin=dict(t=60, l=80, r=20, b=80),
    )
    return fig


def _build_rubric_distribution(
    results: list[EvaluationResult],
) -> "go.Figure":
    """Stacked bar chart of how many rows hit each rubric level (1-5).
    Only renders when the Rubrics score was actually computed."""
    rubric_scores: list[int] = []
    for result in results:
        raw = result.scores.get("Rubrics score")
        if raw is None:
            continue
        try:
            rubric_scores.append(int(round(float(raw))))
        except (TypeError, ValueError):
            continue

    fig = go.Figure()
    if not rubric_scores:
        fig.add_annotation(
            text="No Rubrics score in this run.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        fig.update_layout(template="plotly_dark", height=300)
        return fig

    counts = {level: rubric_scores.count(level) for level in range(1, 6)}
    df = pd.DataFrame(
        [{"Level": str(k), "Count": v} for k, v in counts.items()]
    )
    level_colors = {
        "1": "#fb7185",  # neon-red
        "2": "#fbbf24",  # neon-amber
        "3": "#94a3b8",  # dim
        "4": "#a3e635",  # neon-lime
        "5": "#22d3ee",  # neon-cyan
    }
    fig = px.bar(
        df,
        x="Level",
        y="Count",
        color="Level",
        color_discrete_map=level_colors,
        text="Count",
        title="Rubric Score Distribution (1 = worst, 5 = best)",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        template="plotly_dark",
        height=360,
        margin=dict(t=60, l=50, r=20, b=50),
        showlegend=False,
        yaxis=dict(rangemode="tozero"),
    )
    return fig


def _build_pass_fail_donuts(
    results: list[EvaluationResult],
    metric_names: list[str],
) -> "go.Figure":
    """One donut chart per metric showing pass/fail vs the recommended
    minimum. Pass = neon-lime, fail = neon-amber, missing = dim."""
    fig = go.Figure()
    if not metric_names or not results:
        fig.add_annotation(
            text="No metrics to chart.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        fig.update_layout(template="plotly_dark", height=300)
        return fig

    n_metrics = len(metric_names)
    cols = min(4, n_metrics)
    rows = (n_metrics + cols - 1) // cols
    subplot_index = 1
    annotations: list[dict[str, Any]] = []
    for metric_name in metric_names:
        pass_count = 0
        fail_count = 0
        missing_count = 0
        recommendation = get_metric_recommendation(metric_name)
        recommended_min = float(recommendation["min"])
        for result in results:
            score = result.scores.get(metric_name)
            if score is None:
                missing_count += 1
            elif float(score) >= recommended_min:
                pass_count += 1
            else:
                fail_count += 1

        labels = ["Pass", "Fail", "Missing"]
        values = [pass_count, fail_count, missing_count]
        colors = ["#a3e635", "#fbbf24", "#94a3b8"]
        # Skip "Missing" slice if zero so the donut isn't dominated by it.
        filtered = [
            (label, value, color)
            for label, value, color in zip(labels, values, colors)
            if value > 0
        ]
        if not filtered:
            continue
        labels_f, values_f, colors_f = zip(*filtered)
        col_index = (subplot_index - 1) % cols
        row_index = (subplot_index - 1) // cols
        # domain.x and domain.y must be 2-element lists
        # [start, end] in paper coordinates, not a single float.
        fig.add_trace(
            go.Pie(
                labels=labels_f,
                values=values_f,
                marker=dict(colors=colors_f),
                hole=0.55,
                title=dict(
                    text=f"{metric_name}<br>"
                    f"<span style='font-size:10px'>min {recommended_min}</span>",
                    font=dict(size=11),
                ),
                textinfo="label+value",
                textposition="outside",
                domain=dict(
                    x=[col_index / cols, (col_index + 1) / cols],
                    y=[1 - (row_index + 1) / rows, 1 - row_index / rows],
                ),
            )
        )
        subplot_index += 1

    fig.update_layout(
        title="Pass / Fail per Metric (green = meets recommended minimum)",
        template="plotly_dark",
        height=180 * rows + 80,
        margin=dict(t=60, l=20, r=20, b=20),
        showlegend=False,
        annotations=annotations,
    )
    return fig


def _format_run_label_from_entry(entry: dict[str, Any]) -> str:
    """Human-readable label for a run-picker dropdown row.

    Prefers the new `title` field, falls back to the legacy `label`
    field, and finally the bare filename. Always appends the saved
    timestamp + row count so two runs with the same title are still
    distinguishable.
    """
    when = entry.get("saved_at", "") or "unknown time"
    title = (
        entry.get("title")
        or entry.get("label")
        or entry.get("filename", "")
    )
    rows = entry.get("row_count", 0)
    return f"{when} · {title} ({rows} row{'s' if rows != 1 else ''})"


def make_run_label_formatter(saved_runs: list[dict[str, Any]]):
    """Build a `format_func` for `st.selectbox` from a list of run entries.

    Streamlit calls `format_func` with the **option value**, not the
    underlying entry. Since the option value here is a bare filename
    string, we need a closure that can look the matching entry up.

    The returned callable is safe to use as a `format_func` and works
    even if the option isn't in the saved_runs list (falls back to the
    raw input).
    """
    entries_by_filename = {entry["filename"]: entry for entry in saved_runs}

    def _format(option: Any) -> str:
        if isinstance(option, dict):
            return _format_run_label_from_entry(option)
        if not isinstance(option, str):
            return str(option)
        entry = entries_by_filename.get(option)
        if entry is not None:
            return _format_run_label_from_entry(entry)
        return option

    return _format


def _suggest_run_title(saved_runs: list[dict[str, Any]]) -> str:
    """Auto-suggest a run title based on the most recent saved run.

    Most users iterate by tweaking one thing at a time, so a numeric
    suffix is a useful prompt: "GLM-4.7 baseline (2)", "(3)", etc.
    Falls back to a generic title if there is no history yet.
    """
    if not saved_runs:
        return "Baseline run"
    last_title = (
        saved_runs[0].get("title")
        or saved_runs[0].get("label")
        or "Run"
    )
    # Increment a trailing " (N)" suffix if present, otherwise add one.
    import re as _re

    match = _re.search(r"\s*\((\d+)\)\s*$", last_title)
    if match:
        next_n = int(match.group(1)) + 1
        base = last_title[: match.start()].rstrip()
        return f"{base} ({next_n})"
    return f"{last_title} (2)"


def _build_history_trend_chart(
    selected_runs: list[dict[str, Any]],
    metric_names: list[str],
) -> "go.Figure":
    """One line per metric, x-axis is run timestamp, y-axis is mean
    score. Includes a thin dashed reference line at each metric's
    recommended minimum.
    """
    fig = go.Figure()
    if not selected_runs or not metric_names:
        fig.add_annotation(
            text="No runs in the selected range.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        fig.update_layout(template="plotly_dark", height=300)
        return fig

    # Distinct color per metric. Uses the same neon palette as the rest
    # of the dashboard for visual continuity.
    metric_colors = [
        "#22d3ee",  # neon-cyan
        "#a3e635",  # neon-lime
        "#f0abfc",  # neon-magenta
        "#fbbf24",  # neon-amber
        "#a855f7",  # neon-violet
        "#fb7185",  # neon-red
        "#94a3b8",  # dim
    ]
    color_for = {name: metric_colors[i % len(metric_colors)] for i, name in enumerate(metric_names)}

    timestamps: list[str] = []
    for entry in selected_runs:
        # The saved_at field is full ISO; the x-axis label is the more
        # compact "MM-DD HH:MM" form so a week of runs fits without
        # rotating. The full timestamp is in the hover.
        ts_raw = entry.get("saved_at", "")
        try:
            dt = datetime.fromisoformat(ts_raw)
            ts_label = dt.strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            ts_label = ts_raw or entry.get("filename", "?")
        timestamps.append(ts_label)

    for metric_name in metric_names:
        means: list[float | None] = []
        hover_labels: list[str] = []
        for entry in selected_runs:
            try:
                payload = _history_load_run(entry["filename"])
            except (OSError, ValueError):
                means.append(None)
                hover_labels.append(entry["filename"])
                continue
            scores = [
                float(r.get("scores", {}).get(metric_name))
                for r in payload.get("results", [])
                if r.get("scores", {}).get(metric_name) is not None
            ]
            if not scores:
                means.append(None)
            else:
                means.append(sum(scores) / len(scores))
            hover_labels.append(payload.get("title", entry.get("filename", "")))

        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=means,
                mode="lines+markers",
                name=metric_name,
                line=dict(color=color_for[metric_name], width=2),
                marker=dict(size=7),
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "When: %{x}<br>"
                    "Run: %{customdata}<br>"
                    "Mean: %{y:.4f}<extra></extra>"
                ),
                customdata=hover_labels,
                connectgaps=False,
            )
        )
        # Reference line at the metric's recommended minimum.
        recommended_min = float(get_metric_recommendation(metric_name)["min"])
        fig.add_hline(
            y=recommended_min,
            line=dict(color=color_for[metric_name], width=1, dash="dot"),
            opacity=0.35,
            annotation_text=f"min {metric_name}",
            annotation_position="right",
            annotation_font_size=9,
            annotation_font_color=color_for[metric_name],
        )

    fig.update_layout(
        title="Score History (mean per metric, oldest → newest)",
        xaxis_title="Run timestamp",
        yaxis_title="Mean Score",
        yaxis=dict(range=[0, 1.05]),
        template="plotly_dark",
        height=460,
        margin=dict(t=60, l=50, r=30, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
        hovermode="x unified",
    )
    return fig


def _build_history_summary_table(
    selected_runs: list[dict[str, Any]],
    metric_names: list[str],
) -> "go.Figure":
    """Table of every selected run with one column per metric. Lets
    you read exact values that the line chart can't show clearly when
    runs are close together in time."""
    rows: list[list[str]] = []
    for entry in selected_runs:
        try:
            payload = _history_load_run(entry["filename"])
        except (OSError, ValueError):
            continue
        means: list[str] = []
        for metric_name in metric_names:
            scores = [
                float(r.get("scores", {}).get(metric_name))
                for r in payload.get("results", [])
                if r.get("scores", {}).get(metric_name) is not None
            ]
            means.append(f"{sum(scores) / len(scores):.4f}" if scores else "—")
        rows.append(
            [
                payload.get("title", entry["filename"]),
                entry.get("saved_at", ""),
                str(len(payload.get("results", []))),
                payload.get("rubric_preset", "—") or "—",
                payload.get("test_set_name", "—") or "—",
            ]
            + means
        )

    fig = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=["Title", "When", "Rows", "Rubric", "Test set", *metric_names],
                    fill_color="#0a0e1c",
                    font=dict(color="#22d3ee", size=12, family="JetBrains Mono, monospace"),
                    align="left",
                    height=32,
                ),
                cells=dict(
                    values=[list(col) for col in zip(*rows)] if rows else [[] for _ in range(5 + len(metric_names))],
                    fill_color="#080a16",
                    font=dict(color="#e2e8f0", size=11, family="JetBrains Mono, monospace"),
                    align="left",
                    height=28,
                ),
            )
        ]
    )
    fig.update_layout(
        title="Run details",
        template="plotly_dark",
        height=120 + 32 * (len(rows) + 1),
        margin=dict(t=60, l=10, r=10, b=10),
    )
    return fig


def _build_compare_delta_table(
    run_a: dict[str, Any],
    run_b: dict[str, Any],
    metric_names: list[str],
) -> "go.Figure":
    """One row per metric, columns: A mean, B mean, Δ mean, A pass, B
    pass, Δ pass. The Δ cells are colored by sign (green = B better,
    amber = B worse)."""
    a_results = run_a.get("results", [])
    b_results = run_b.get("results", [])

    a_pass = {
        metric_name: sum(
            1
            for r in a_results
            if (r.get("scores") or {}).get(metric_name) is not None
            and float((r.get("scores") or {}).get(metric_name))
            >= float(get_metric_recommendation(metric_name)["min"])
        )
        for metric_name in metric_names
    }
    a_total = {
        metric_name: sum(
            1
            for r in a_results
            if (r.get("scores") or {}).get(metric_name) is not None
        )
        for metric_name in metric_names
    }
    b_pass = {
        metric_name: sum(
            1
            for r in b_results
            if (r.get("scores") or {}).get(metric_name) is not None
            and float((r.get("scores") or {}).get(metric_name))
            >= float(get_metric_recommendation(metric_name)["min"])
        )
        for metric_name in metric_names
    }
    b_total = {
        metric_name: sum(
            1
            for r in b_results
            if (r.get("scores") or {}).get(metric_name) is not None
        )
        for metric_name in metric_names
    }

    a_mean = {
        metric_name: (
            sum(
                float((r.get("scores") or {}).get(metric_name))
                for r in a_results
                if (r.get("scores") or {}).get(metric_name) is not None
            )
            / max(1, a_total[metric_name])
        )
        for metric_name in metric_names
    }
    b_mean = {
        metric_name: (
            sum(
                float((r.get("scores") or {}).get(metric_name))
                for r in b_results
                if (r.get("scores") or {}).get(metric_name) is not None
            )
            / max(1, b_total[metric_name])
        )
        for metric_name in metric_names
    }

    def _delta_color(delta: float) -> str:
        if delta > 0.005:
            return "#a3e635"  # neon-lime (better)
        if delta < -0.005:
            return "#fbbf24"  # neon-amber (worse)
        return "#94a3b8"     # dim (no real change)

    metric_col, a_mean_col, b_mean_col, delta_mean_col, a_pass_col, b_pass_col, delta_pass_col = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for metric_name in metric_names:
        delta_mean = b_mean[metric_name] - a_mean[metric_name]
        a_pass_rate = a_pass[metric_name] / max(1, a_total[metric_name])
        b_pass_rate = b_pass[metric_name] / max(1, b_total[metric_name])
        delta_pass = b_pass_rate - a_pass_rate
        metric_col.append(metric_name)
        a_mean_col.append(f"{a_mean[metric_name]:.4f}")
        b_mean_col.append(f"{b_mean[metric_name]:.4f}")
        delta_mean_col.append(
            f"<span style='color:{_delta_color(delta_mean)}'>"
            f"{'+' if delta_mean >= 0 else ''}{delta_mean:+.4f}</span>"
        )
        a_pass_col.append(f"{a_pass[metric_name]}/{a_total[metric_name]}")
        b_pass_col.append(f"{b_pass[metric_name]}/{b_total[metric_name]}")
        delta_pass_col.append(
            f"<span style='color:{_delta_color(delta_pass)}'>"
            f"{'+' if delta_pass >= 0 else ''}{delta_pass:+.0%}</span>"
        )

    fig = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=[
                        "<b>Metric</b>",
                        f"<b>{run_a.get('title', 'A')}</b><br><span style='font-size:9px'>mean</span>",
                        f"<b>{run_b.get('title', 'B')}</b><br><span style='font-size:9px'>mean</span>",
                        "<b>Δ mean</b>",
                        f"<b>{run_a.get('title', 'A')}</b><br><span style='font-size:9px'>pass/total</span>",
                        f"<b>{run_b.get('title', 'B')}</b><br><span style='font-size:9px'>pass/total</span>",
                        "<b>Δ pass-rate</b>",
                    ],
                    fill_color="#0a0e1c",
                    font=dict(color="#22d3ee", size=12, family="JetBrains Mono, monospace"),
                    align="left",
                    height=44,
                ),
                cells=dict(
                    values=[
                        metric_col,
                        a_mean_col,
                        b_mean_col,
                        delta_mean_col,
                        a_pass_col,
                        b_pass_col,
                        delta_pass_col,
                    ],
                    fill_color="#080a16",
                    font=dict(color="#e2e8f0", size=11, family="JetBrains Mono, monospace"),
                    align="left",
                    height=30,
                ),
            )
        ]
    )
    fig.update_layout(
        title="Metric-level delta (green = B better, amber = B worse)",
        template="plotly_dark",
        height=120 + 30 * (len(metric_names) + 1),
        margin=dict(t=60, l=10, r=10, b=10),
    )
    return fig


def _build_compare_grouped_bar(
    run_a: dict[str, Any],
    run_b: dict[str, Any],
    metric_names: list[str],
) -> "go.Figure":
    """Grouped bar chart: A vs B mean score per metric."""
    def _mean_for(run: dict[str, Any], metric_name: str) -> float | None:
        results = run.get("results", [])
        scores = [
            float((r.get("scores") or {}).get(metric_name))
            for r in results
            if (r.get("scores") or {}).get(metric_name) is not None
        ]
        return sum(scores) / len(scores) if scores else None

    a_means = [_mean_for(run_a, m) for m in metric_names]
    b_means = [_mean_for(run_b, m) for m in metric_names]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name=run_a.get("title", "Run A"),
            x=metric_names,
            y=a_means,
            marker_color="#22d3ee",
            text=[f"{v:.3f}" if v is not None else "—" for v in a_means],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            name=run_b.get("title", "Run B"),
            x=metric_names,
            y=b_means,
            marker_color="#a3e635",
            text=[f"{v:.3f}" if v is not None else "—" for v in b_means],
            textposition="outside",
        )
    )
    for metric_name in metric_names:
        fig.add_hline(
            y=float(get_metric_recommendation(metric_name)["min"]),
            line=dict(color="#a855f7", width=1, dash="dot"),
            opacity=0.3,
        )
    fig.update_layout(
        title="Mean score: A vs B",
        barmode="group",
        template="plotly_dark",
        height=420,
        yaxis=dict(range=[0, 1.05]),
        margin=dict(t=60, l=50, r=30, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
    )
    return fig


def _normalize_question(text: str) -> str:
    """Lowercase + collapse whitespace so two runs with the same
    question but slightly different formatting still match."""
    return " ".join((text or "").lower().split())


def _build_per_question_compare(
    run_a: dict[str, Any],
    run_b: dict[str, Any],
    metric_names: list[str],
) -> "go.Figure":
    """Per-question delta chart. Matches rows by question text
    (case-insensitive, whitespace-normalized) so the comparison stays
    stable even if the row order changed between runs."""
    a_by_q = {_normalize_question(r.get("question", "")): r for r in run_a.get("results", [])}
    b_by_q = {_normalize_question(r.get("question", "")): r for r in run_b.get("results", [])}
    shared_keys = sorted(set(a_by_q) & set(b_by_q))

    if not shared_keys:
        fig = go.Figure()
        fig.add_annotation(
            text="No shared questions between Run A and Run B.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
        )
        fig.update_layout(template="plotly_dark", height=300)
        return fig

    fig = go.Figure()
    for metric_name in metric_names:
        a_vals: list[float] = []
        b_vals: list[float] = []
        deltas: list[float] = []
        labels: list[str] = []
        for key in shared_keys:
            a_score = (a_by_q[key].get("scores") or {}).get(metric_name)
            b_score = (b_by_q[key].get("scores") or {}).get(metric_name)
            if a_score is None or b_score is None:
                continue
            a_vals.append(float(a_score))
            b_vals.append(float(b_score))
            deltas.append(float(b_score) - float(a_score))
            # Truncate the question text for the axis label
            labels.append(a_by_q[key].get("question", key)[:40])

        if not deltas:
            continue
        bar_colors = ["#a3e635" if d > 0.005 else "#fbbf24" if d < -0.005 else "#94a3b8" for d in deltas]
        fig.add_trace(
            go.Bar(
                name=metric_name,
                x=labels,
                y=deltas,
                marker_color=bar_colors,
                hovertemplate=(
                    f"<b>%{{x}}</b><br>"
                    f"Metric: {metric_name}<br>"
                    "Δ: %{y:+.4f}<br>"
                    "A: %{customdata[0]:.4f}<br>"
                    "B: %{customdata[1]:.4f}<extra></extra>"
                ),
                customdata=list(zip(a_vals, b_vals)),
            )
        )
    fig.add_hline(
        y=0,
        line=dict(color="#22d3ee", width=1),
    )
    fig.update_layout(
        title="Per-question delta (B − A; green = B better, amber = B worse)",
        barmode="group",
        template="plotly_dark",
        height=460,
        margin=dict(t=60, l=50, r=30, b=120),
        xaxis_tickangle=-30,
        legend=dict(orientation="h", yanchor="bottom", y=-0.45, xanchor="center", x=0.5),
    )
    return fig


def _render_run_header(
    label: str,
    run: dict[str, Any],
) -> None:
    """Render a single run's metadata as a markdown callout so the
    comparison header reads at a glance."""
    title = run.get("title", run.get("label", "(untitled)"))
    when = run.get("saved_at", "")
    rubric = run.get("rubric_preset", "—") or "—"
    test_set = run.get("test_set_name", "—") or "—"
    description = (run.get("description") or "").strip()
    rows = len(run.get("results", []))

    body = (
        f"**{label}: {html.escape(title)}**  \n"
        f"`{html.escape(when)}` · {rows} row{'s' if rows != 1 else ''} · "
        f"Rubric: **{html.escape(rubric)}** · Test set: *{html.escape(test_set)}*"
    )
    if description:
        body += f"\n\n> {html.escape(description)}"
    st.markdown(body)


def _warn_on_different_conditions(run_a: dict[str, Any], run_b: dict[str, Any]) -> None:
    """Surface a warning banner when the two runs used different
    rubrics, test sets, or row counts — the most common source of
    confusing comparison results."""
    warnings: list[str] = []
    if (run_a.get("rubric_preset") or "") != (run_b.get("rubric_preset") or ""):
        warnings.append(
            f"**Different rubric presets** — A: `{run_a.get('rubric_preset') or '—'}`, "
            f"B: `{run_b.get('rubric_preset') or '—'}`. Rubric-scored metrics "
            "(e.g. Rubrics score) are not directly comparable."
        )
    if (run_a.get("test_set_name") or "") != (run_b.get("test_set_name") or ""):
        warnings.append(
            f"**Different test sets** — A: `{run_a.get('test_set_name') or '—'}`, "
            f"B: `{run_b.get('test_set_name') or '—'}`. Per-row deltas only "
            "show rows that appear in both runs."
        )
    if len(run_a.get("results", [])) != len(run_b.get("results", [])):
        warnings.append(
            f"**Different row counts** — A: {len(run_a.get('results', []))}, "
            f"B: {len(run_b.get('results', []))}. Mean scores are still "
            "comparable but the per-row chart will be uneven."
        )
    for warning in warnings:
        st.warning(warning, icon="⚠️")


def render_analytics_tab() -> None:
    """Render the Analytics tab: 4 charts over the current results, plus
    Save/Load/Delete controls that work with the JSON-file history."""
    inject_dashboard_styles()
    results: list[EvaluationResult] = st.session_state.get("evaluation_results", [])

    st.subheader("Analytics")

    # ----- Save / Load controls -----
    saved_runs = _history_list_runs()
    save_col, load_col, delete_col = st.columns([1.4, 1.4, 1.0])

    with save_col:
        st.markdown("**Save current run**")
        # Auto-suggest a title the first time the dialog is opened in
        # this session, and any time the user clears the field after
        # they have typed something.
        if "save_title" not in st.session_state or st.session_state.get(
            "save_title_autofilled", True
        ):
            st.session_state["save_title"] = _suggest_run_title(saved_runs)
            st.session_state["save_title_autofilled"] = False
        st.text_input(
            "Title (required)",
            value=st.session_state.get("save_title", ""),
            key="save_title_widget",
            placeholder="e.g. 'GLM-4.7 baseline'",
            help=(
                "One-line identifier shown in the comparison header. "
                "Most users iterate by tweaking one thing, so the next "
                "title is auto-suggested as '<previous> (N)'."
            ),
        )
        st.session_state["save_title"] = st.session_state.get("save_title_widget", "")
        st.text_area(
            "Description (optional)",
            value=st.session_state.get("save_description", ""),
            key="save_description_widget",
            placeholder=(
                "e.g. 'Changed system prompt to be more concise. "
                "Same 3 questions as baseline.'"
            ),
            help="Free-form context shown in the comparison header.",
            height=80,
        )
        st.session_state["save_description"] = st.session_state.get(
            "save_description_widget", ""
        )
        # Auto-fill test set name and rubric from the active session,
        # but let the user override (e.g. if they ran an ad-hoc test
        # outside the CSV).
        active_test_set = os.getenv("ARIA_DATA_FILE", "")
        if not active_test_set:
            active_test_set = "testdata/ARIA_data.csv"
        active_test_set = f"{Path(active_test_set).name} ({len(results)} row{'s' if len(results) != 1 else ''})"
        st.text_input(
            "Test set (auto)",
            value=st.session_state.get("save_test_set_name", active_test_set),
            key="save_test_set_widget",
            help=(
                "Auto-filled from ARIA_DATA_FILE + row count. Edit if "
                "you ran an ad-hoc test."
            ),
        )
        st.session_state["save_test_set_name"] = st.session_state.get(
            "save_test_set_widget", active_test_set
        )
        active_rubric = st.session_state.get(
            "rubric_preset_name", DEFAULT_RUBRIC_PRESET
        )
        st.text_input(
            "Rubric preset (auto)",
            value=st.session_state.get("save_rubric_preset", active_rubric),
            key="save_rubric_preset_widget",
            help="Auto-filled from the active rubric in the Config tab.",
        )
        st.session_state["save_rubric_preset"] = st.session_state.get(
            "save_rubric_preset_widget", active_rubric
        )
        if st.button("Save this run", use_container_width=True, disabled=not results):
            if not results:
                st.warning("Run an evaluation first.")
            else:
                config: AppConfig | None = st.session_state.get("evaluation_config")
                path = _history_save_run(
                    results,
                    config,
                    title=st.session_state.get("save_title", "").strip(),
                    description=st.session_state.get("save_description", "").strip(),
                    test_set_name=st.session_state.get("save_test_set_name", "").strip(),
                    rubric_preset=st.session_state.get("save_rubric_preset", "").strip(),
                )
                # Once the user has saved once, the auto-suggest should
                # refresh on the next save (not stick to the just-used
                # title). Re-enable auto-fill so the next save gets a
                # fresh "<title> (N+1)" suggestion.
                st.session_state["save_title_autofilled"] = True
                st.success(f"Saved to `{path.name}`")
                st.rerun()

    with load_col:
        st.markdown("**Load a previous run**")
        if saved_runs:
            options = [entry["filename"] for entry in saved_runs]
            selected_filename = st.selectbox(
                "Saved runs",
                options=options,
                format_func=make_run_label_formatter(saved_runs),
                key="load_run_select",
                label_visibility="collapsed",
            )
            if st.button("Load into Results tab", use_container_width=True):
                try:
                    payload = _history_load_run(selected_filename)
                    # Hydrate session_state so Results + Analytics reflect
                    # the loaded run as if you had just run it.
                    st.session_state["evaluation_results"] = _payload_to_results(
                        payload.get("results", [])
                    )
                    if "config" in payload:
                        st.session_state["evaluation_config"] = _payload_to_config(
                            payload["config"]
                        )
                    st.success(f"Loaded {selected_filename}.")
                    st.rerun()
                except FileNotFoundError:
                    st.error("File no longer exists on disk.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Failed to load: {exc}")
        else:
            st.caption("No saved runs yet.")

    with delete_col:
        st.markdown("**History folder**")
        st.code(str(_history_dir()), language=None)
        if saved_runs:
            file_to_delete = st.selectbox(
                "Delete a run",
                options=[entry["filename"] for entry in saved_runs],
                format_func=make_run_label_formatter(saved_runs),
                key="delete_run_select",
                label_visibility="collapsed",
            )
            if st.button("Delete", use_container_width=True, type="secondary"):
                if _history_delete_run(file_to_delete):
                    st.success(f"Deleted `{file_to_delete}`.")
                    st.rerun()
                else:
                    st.error("File not found.")

    st.divider()

    # View mode toggles between "current run only" (the 4 charts above)
    # and "history & compare" (trend chart + side-by-side comparison).
    # Default to "current" when there are no saved runs.
    if not saved_runs:
        view_mode = "Current run"
    else:
        view_mode = st.radio(
            "View mode",
            options=["Current run", "History & compare"],
            index=0,
            horizontal=True,
            key="analytics_view_mode",
        )

    if view_mode == "History & compare":
        _render_history_and_compare_section(saved_runs)
        return

    if not results:
        st.info(
            "Run an evaluation from the **Config** tab — the four charts "
            "below will populate automatically. You can also load a "
            "previously saved run from the picker above."
        )
        return

    # Apply the live multiselect filter so the charts match the Results tab.
    filtered = _filter_results_to_active_metrics(results)
    metric_names = (
        get_metric_order(filtered[0].scores.keys()) if filtered else []
    )
    if not metric_names:
        st.info("No metrics selected. Pick at least one in the Config tab.")
        return

    # Build a stable container per chart so the page has a clear visual rhythm.
    with st.container():
        st.plotly_chart(
            _build_avg_bar_chart(filtered, metric_names),
            use_container_width=True,
        )

    st.plotly_chart(
        _build_heatmap(filtered, metric_names),
        use_container_width=True,
    )

    if any("Rubrics score" in r.scores for r in filtered):
        st.plotly_chart(
            _build_rubric_distribution(filtered),
            use_container_width=True,
        )

    st.plotly_chart(
        _build_pass_fail_donuts(filtered, metric_names),
        use_container_width=True,
    )

    st.caption(
        f"Charts reflect the **{len(filtered)}** row(s) and "
        f"**{len(metric_names)}** metric(s) currently selected. "
        "Save the run before changing the CSV or metric list if you "
        "want to compare later."
    )


def _render_history_and_compare_section(
    saved_runs: list[dict[str, Any]],
) -> None:
    """Render the History & compare view: a trend line chart over the
    selected date range, a summary table, and a side-by-side compare
    view for any two saved runs."""
    st.subheader("History & compare")

    if not saved_runs:
        st.info("No saved runs yet. Save a run above to enable history.")
        return

    # ----- Trend chart -----
    st.markdown("### Score history")
    range_label = st.radio(
        "Time range",
        options=["Last 7 days", "Last 30 days", "All time"],
        index=1,
        horizontal=True,
        key="history_range",
    )
    days_map = {"Last 7 days": 7, "Last 30 days": 30, "All time": None}
    selected_runs = _history_runs_in_date_range(days_map[range_label])

    if not selected_runs:
        st.info(f"No runs found in {range_label.lower()}.")
        return

    # Determine the set of metrics that appear in at least one of the
    # selected runs. This avoids "no data" gaps when a metric was added
    # or removed between runs.
    metric_set: set[str] = set()
    for entry in selected_runs:
        try:
            payload = _history_load_run(entry["filename"])
        except (OSError, ValueError):
            continue
        for result in payload.get("results", []):
            metric_set.update((result.get("scores") or {}).keys())
    metric_names = get_metric_order(metric_set)

    # If there are many metrics, let the user pick which ones to show on
    # the line chart (otherwise the legend overflows).
    if len(metric_names) > 7:
        selected_chart_metrics = st.multiselect(
            "Metrics to plot (chart becomes unreadable past ~7 lines)",
            options=metric_names,
            default=metric_names[:7],
            key="trend_chart_metric_filter",
        )
        if not selected_chart_metrics:
            st.warning("Select at least one metric to draw the trend chart.")
            return
        metric_names = selected_chart_metrics

    st.plotly_chart(
        _build_history_trend_chart(selected_runs, metric_names),
        use_container_width=True,
    )
    st.plotly_chart(
        _build_history_summary_table(selected_runs, metric_names),
        use_container_width=True,
    )

    st.divider()

    # ----- Side-by-side compare -----
    st.markdown("### Compare two runs")
    compare_options = [entry["filename"] for entry in saved_runs]
    # Build a single format_func that looks up the matching entry by
    # filename. Streamlit passes the raw option value (a string here)
    # to format_func, so we need a closure that knows about saved_runs.
    compare_format_func = make_run_label_formatter(saved_runs)
    compare_a, compare_b, compare_btn = st.columns([1.5, 1.5, 0.6])
    with compare_a:
        run_a_filename = st.selectbox(
            "Run A (baseline)",
            options=compare_options,
            index=1 if len(compare_options) > 1 else 0,
            format_func=compare_format_func,
            key="compare_run_a",
        )
    with compare_b:
        run_b_filename = st.selectbox(
            "Run B (candidate)",
            options=compare_options,
            index=0,
            format_func=compare_format_func,
            key="compare_run_b",
        )
    with compare_btn:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        compare_clicked = st.button(
            "Compare",
            use_container_width=True,
            type="primary",
            key="compare_btn",
        )

    if run_a_filename == run_b_filename:
        st.caption("Pick two different runs to compare.")
        return

    if not compare_clicked:
        st.caption("Click **Compare** to compute the delta.")
        return

    try:
        run_a_payload = _history_load_run(run_a_filename)
        run_b_payload = _history_load_run(run_b_filename)
    except (OSError, ValueError) as exc:
        st.error(f"Failed to load runs: {exc}")
        return

    # Side-by-side header with the saved metadata for each run, plus
    # warning banners when the two runs used different conditions.
    head_a, head_b = st.columns(2)
    with head_a:
        _render_run_header("Run A", run_a_payload)
    with head_b:
        _render_run_header("Run B", run_b_payload)
    _warn_on_different_conditions(run_a_payload, run_b_payload)

    # Union of metrics across both runs so a metric that exists only in
    # one still shows up in the delta.
    compare_metric_set: set[str] = set()
    for run_payload in (run_a_payload, run_b_payload):
        for result in run_payload.get("results", []):
            compare_metric_set.update((result.get("scores") or {}).keys())
    compare_metric_names = get_metric_order(compare_metric_set)

    st.plotly_chart(
        _build_compare_delta_table(run_a_payload, run_b_payload, compare_metric_names),
        use_container_width=True,
    )
    st.plotly_chart(
        _build_compare_grouped_bar(run_a_payload, run_b_payload, compare_metric_names),
        use_container_width=True,
    )
    st.plotly_chart(
        _build_per_question_compare(run_a_payload, run_b_payload, compare_metric_names),
        use_container_width=True,
    )


def _payload_to_results(payload_results: list[dict[str, Any]]) -> list[EvaluationResult]:
    """Re-hydrate a list of result dicts from a saved JSON file into
    EvaluationResult instances."""
    out: list[EvaluationResult] = []
    for record in payload_results:
        out.append(
            EvaluationResult(
                row_number=int(record.get("row_number", 0)),
                question=str(record.get("question", "")),
                response=str(record.get("response", "")),
                reference=str(record.get("reference", "")),
                retrieved_contexts=list(record.get("retrieved_contexts", [])),
                scores=dict(record.get("scores", {})),
                reasons=dict(record.get("reasons", {})),
            )
        )
    return out


def _payload_to_config(payload: dict[str, Any]) -> AppConfig:
    """Re-hydrate an AppConfig from a saved JSON dict. Uses a placeholder
    API key (the live one is always read from 1.env at score time)."""
    return AppConfig(
        rag_endpoint=str(payload.get("rag_endpoint", "")),
        llm_api_key=os.getenv("OPENAI_API_KEY", ""),
        llm_api_endpoint=str(payload.get("llm_api_endpoint", "")),
        llm_model=str(payload.get("llm_model", "")),
        llm_temperature=float(payload.get("llm_temperature", 0.0)),
        llm_max_tokens=int(payload.get("llm_max_tokens", 8192)),
        selected_metrics=list(payload.get("selected_metrics", AVAILABLE_METRICS)),
        rows=[],  # Rows aren't stored on config; they're in the results.
    )

def validate_review_rows(
    review_rows: list[dict[str, Any]], selected_metrics: list[str]
) -> str | None:
    """Make sure the user has filled in all the fields required by the
    metrics they selected. Returns a human-readable error string, or
    None if everything is fine."""
    requires_response = bool(set(selected_metrics) & METRICS_REQUIRING_RESPONSE)
    requires_reference = bool(set(selected_metrics) & METRICS_REQUIRING_REFERENCE)
    requires_contexts = bool(set(selected_metrics) & METRICS_REQUIRING_CONTEXTS)

    for review_row in review_rows:
        row_number = review_row["row_number"]
        if not review_row["question"]:
            return f"Row {row_number} is missing the query."
        if requires_response and not review_row["response"]:
            return f"Row {row_number} is missing the response required for the selected metrics."
        if requires_reference and not review_row["reference"]:
            return f"Row {row_number} is missing the reference required for the selected metrics."
        if requires_contexts and not review_row["retrieved_contexts"]:
            return f"Row {row_number} needs at least one retrieved context for the selected metrics."

    return None


def render_review_stage() -> None:
    """Render the Step 1 review UI: for each row, show the question,
    response, reference, and contexts the RAG system returned, with
    editable text boxes. A 'Step 2' button triggers the metric scoring."""
    review_rows: list[dict[str, Any]] = st.session_state.get("review_rows", [])
    config: AppConfig | None = st.session_state.get("evaluation_config")

    if not review_rows or config is None:
        return

    st.markdown("### Step 1 Review")
    st.caption(
        "Step 1 queried the RAG system. Review and edit the query, response, reference, and retrieved contexts before running step 2 metrics."
    )

    for review_row in review_rows:
        row_number = review_row["row_number"]
        with st.expander(f"Row {row_number}: {review_row['question']}", expanded=(row_number == 1)):
            st.text_area(
                "Query",
                key=f"review_question_{row_number}",
                height=80,
            )
            st.text_area(
                "Response",
                key=f"review_response_{row_number}",
                height=140,
            )
            st.text_area(
                "Reference",
                key=f"review_reference_{row_number}",
                height=140,
            )

            st.markdown(f"#### Retrieved Contexts ({len(review_row['retrieved_contexts'])})")
            for context_index, _ in enumerate(review_row["retrieved_contexts"], start=1):
                st.text_area(
                    f"Context {context_index}",
                    key=f"review_context_{row_number}_{context_index}",
                    height=140,
                )

    if st.button("Step 2: Run Metrics", use_container_width=True):
        updated_review_rows = collect_review_rows(review_rows)
        validation_error = validate_review_rows(updated_review_rows, config.selected_metrics)
        if validation_error:
            st.error(validation_error)
            return

        with st.spinner(f"Running metrics for {len(updated_review_rows)} reviewed row(s)..."):
            try:
                st.session_state["review_rows"] = updated_review_rows
                st.session_state["evaluation_results"] = run_async(
                    evaluate_review_rows(config, updated_review_rows)
                )
            except Exception as exc:
                st.error(f"Step 2 failed: {exc}")
                return

        st.success("Step 2 completed. Open the Results tab to inspect the updated metrics.")


def render_config_tab(default_config: AppConfig) -> None:
    """Render the 'Config' tab: the settings form, the editable test rows,
    and the Step 1/Step 2 workflow buttons."""
    active_config: AppConfig = st.session_state.get("evaluation_config", default_config)
    # If the sidebar provider picker just wrote new endpoint/model values,
    # reflect them into active_config so the form starts with them.
    if st.session_state.get("provider_endpoint"):
        active_config = AppConfig(
            rag_endpoint=active_config.rag_endpoint,
            llm_api_key=active_config.llm_api_key,
            llm_api_endpoint=st.session_state["provider_endpoint"],
            llm_model=st.session_state.get("provider_model", active_config.llm_model),
            llm_temperature=active_config.llm_temperature,
            llm_max_tokens=active_config.llm_max_tokens,
            selected_metrics=active_config.selected_metrics,
            rows=active_config.rows,
        )
        st.session_state["evaluation_config"] = active_config
    st.subheader("Configuration")

    # The Rubrics editor lives OUTSIDE the form so its text-area state
    # survives a Step-1 rerun (Streamlit form widgets lose unsaved input
    # when the form is submitted, and the user expects rubric edits to
    # persist into the next evaluation).
    render_rubric_editor()

    # ----- LIVE CONFIGURATION (outside the form) -----
    # Why outside the form? Widgets inside st.form are only persisted to
    # session_state on submit, so a metric / endpoint change would not
    # be visible on the Results tab until the user clicked Step 1. By
    # putting the LLM endpoint/model and the metric picker outside the
    # form, every change takes effect immediately.
    #
    # Layout (left-to-right, top-to-bottom):
    #   Row 1: LLM Model            | LLM API Endpoint
    #   Row 2: Metrics to run      (full width)
    # This keeps LLM settings visually grouped together and gives the
    # metric multiselect a full-width row so the long metric names
    # don't truncate.
    with st.container(border=True):
        st.markdown("#### Live configuration")
        st.caption(
            "Changes here take effect immediately. The form below submits the "
            "rows to RAG and triggers Step 2."
        )

        llm_col_model, llm_col_endpoint = st.columns(2)
        with llm_col_model:
            st.text_input(
                "LLM Model",
                value=st.session_state.get("llm_model_input", active_config.llm_model),
                key="llm_model_input",
                help=(
                    "The judge-LLM model name passed to the OpenAI-compatible "
                    "endpoint. Change here to reroute scoring to a different "
                    "model without restarting the app."
                ),
            )
        with llm_col_endpoint:
            st.text_input(
                "LLM API Endpoint",
                value=st.session_state.get(
                    "llm_api_endpoint_input", active_config.llm_api_endpoint
                ),
                key="llm_api_endpoint_input",
                help=(
                    "Base URL of the OpenAI-compatible chat-completions "
                    "endpoint. Updated by the sidebar's Provider dropdown."
                ),
            )

        # Build the metric options (exclude always-on so the user can't
        # deselect them). Seed the multiselect with the user's previous
        # selection if any, otherwise with every optional metric on.
        user_options = [
            metric_name
            for metric_name in AVAILABLE_METRICS
            if metric_name not in ALWAYS_SELECTED_METRICS
        ]
        if "metrics_multiselect" not in st.session_state:
            st.session_state["metrics_multiselect"] = [
                metric_name
                for metric_name in active_config.selected_metrics
                if metric_name not in ALWAYS_SELECTED_METRICS
            ]
        st.multiselect(
            "Metrics to run",
            options=user_options,
            key="metrics_multiselect",
            help=(
                "Optional metrics. Rubrics score is always included and is "
                "edited above. Changes apply to the Results tab immediately; "
                "rerun Step 2 to score newly added metrics."
            ),
        )

    # ----- TEST DATA (the live data editor) -----
    # Why outside the form? The data_editor inside st.form has a known
    # issue where pre-populated rows can be silently dropped on submit.
    # By mounting it on its own with a stable key, the editor's value
    # is always live in session_state.
    #
    # Two-state strategy:
    #   1. `rows_data_initial` — our own non-widget key. Holds the
    #      source-of-truth DataFrame. We write to it freely.
    #   2. `rows_editor_<sig>` — the widget's own key. Streamlit owns
    #      this; we never assign to it directly (which would raise
    #      StreamlitValueAssignmentNotAllowedError). We only pass the
    #      initial value as a `value=` argument and let Streamlit manage
    #      the rest.
    #
    # IMPORTANT: do NOT include a literal `|` in the widget key. Streamlit
    # parses widget keys on `|` and treats the right side as a chained
    # value, so any pipe in our suffix gets re-interpreted and triggers
    # StreamlitValueAssignmentNotAllowedError on the next rerun.
    with st.container(border=True):
        st.markdown("#### Test data")
        st.caption(
            "One row per question to evaluate. Edit directly — use the + "
            "and trash icons to add or remove rows. Changes here feed the "
            "next Step 1 query."
        )
        _rows_signature = (
            f"{len(active_config.rows)}-"
            f"{active_config.rows[0].question[:30] if active_config.rows else ''}"
        )
        # Sanitize the signature so any `|` or other Streamlit-reserved
        # characters that sneak in (e.g. via unusual question text) don't
        # produce a forbidden widget key.
        _rows_signature = _rows_signature.replace("|", "_")
        _editor_key = f"rows_editor_{_rows_signature}"
        _initial_key = "rows_data_initial"

        # Seed the source-of-truth frame on first load and any time the
        # underlying active_config.rows changes (e.g. CSV reloaded with a
        # different row count, sidebar provider swap, etc.).
        _current_seed_signature = st.session_state.get("rows_data_seed_signature")
        if _current_seed_signature != _rows_signature:
            st.session_state[_initial_key] = build_rows_dataframe(active_config.rows)
            st.session_state["rows_data_seed_signature"] = _rows_signature

        edited_rows = st.data_editor(
            st.session_state[_initial_key],
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=_editor_key,
            column_config={
                "Question": st.column_config.TextColumn(required=True, width="large"),
                "Ground Truth": st.column_config.TextColumn(required=True, width="large"),
            },
        )
        # Mirror the editor's current value into our non-widget key so any
        # other place that reads `st.session_state["rows_data_initial"]`
        # sees the same data the user is looking at.
        st.session_state[_initial_key] = edited_rows
        st.caption(
            f"Editor shows **{len(edited_rows)}** row(s)."
        )

    # ----- RUN SETTINGS (form) -----
    # Settings that get committed together with the Step 1 button.
    # LLM Model / Endpoint / Metrics live outside the form so they
    # take effect on the Results tab immediately.
    with st.container(border=True):
        st.markdown("#### Run")
        with st.form("evaluation_form"):
            run_col_a, run_col_b = st.columns(2)

            with run_col_a:
                llm_temperature = st.number_input(
                    "LLM Temperature",
                    min_value=0.0,
                    max_value=2.0,
                    value=float(active_config.llm_temperature),
                    step=0.1,
                    help="Lower = more deterministic. 0 is recommended for metric scoring.",
                )
                llm_max_tokens = st.number_input(
                    "LLM Max Tokens",
                    min_value=512,
                    max_value=32768,
                    value=int(active_config.llm_max_tokens),
                    step=512,
                    help="Upper bound on the judge LLM's reply. Raise this if scoring fails on long contexts.",
                )

            with run_col_b:
                st.caption(
                    "**Step 1** queries the RAG system for every row and lets "
                    "you review the answer + retrieved contexts. "
                    "**Step 2** then runs the selected metrics on that data."
                )

            run_evaluation = st.form_submit_button(
                "Step 1: Query RAG and Review",
                use_container_width=True,
            )

    if not run_evaluation:
        render_review_stage()
        return

    rows = parse_rows(edited_rows)
    if not rows:
        st.error("Add at least one valid question and ground truth row.")
        return

    for row in rows:
        if not row.question:
            st.error("Each row must include a question.")
            return
        if not row.reference:
            st.error("Each row must include a ground truth value.")
            return

    # Read the live (outside-form) inputs so changes the user just made
    # are honored at submit time. Fall back to the stored config values
    # if the live widgets were never rendered.
    selected_metrics_input = st.session_state.get(
        "metrics_multiselect",
        [
            metric_name
            for metric_name in active_config.selected_metrics
            if metric_name not in ALWAYS_SELECTED_METRICS
        ],
    )
    llm_model = st.session_state.get("llm_model_input", active_config.llm_model)
    llm_api_endpoint = st.session_state.get(
        "llm_api_endpoint_input", active_config.llm_api_endpoint
    )

    # Lock in the always-on metrics (Rubrics score) alongside the user's pick.
    selected_metrics = normalize_selected_metrics(selected_metrics_input)
    if not selected_metrics:
        st.error("Select at least one metric.")
        return

    config = AppConfig(
        rag_endpoint=active_config.rag_endpoint,
        llm_api_key=default_config.llm_api_key,
        llm_api_endpoint=llm_api_endpoint.strip(),
        llm_model=llm_model.strip(),
        llm_temperature=float(llm_temperature),
        llm_max_tokens=int(llm_max_tokens),
        selected_metrics=selected_metrics,
        rows=rows,
    )

    with st.spinner(f"Step 1: querying the RAG system for {len(rows)} row(s)..."):
        try:
            review_rows = build_review_rows(config)
        except Exception as exc:
            st.error(f"Step 1 failed: {exc}")
            return

    st.session_state["evaluation_config"] = config
    st.session_state["review_rows"] = review_rows
    st.session_state["evaluation_results"] = []
    seed_review_widget_state(review_rows)

    st.success("Step 1 completed. Review the fetched data below, make changes if needed, then run Step 2.")
    render_review_stage()


def render_score_cards(
    scores: dict[str, float],
    reasons: dict[str, str] | None = None,
) -> None:
    """Render one row of equal-height 'metric cards' per RAG stage
    (Retrieval / Augmentation / Generation).

    All cards in a row share the same height and align the score number
    on the same baseline, regardless of how long the metric label is.
    The score number is green if the score meets the recommended
    minimum and yellow if it doesn't.

    If a metric produced a judge-LLM reason, it is shown in a "Why this
    score?" expander below the card. The Rubrics metric also gets a
    description box that explains its 1-5 level.

    Inline styles are used for the row + card layout so the equal-height
    alignment works even if the global <style> block from st.html(...)
    fails to reach the browser (Streamlit WebSocket re-connect issues
    can drop the theme).
    """
    reasons = reasons or {}
    # Same filter as the dashboard: only show metrics the user actually
    # selected for the most recent evaluation (Rubrics score stays visible
    # because it's always-on).
    active_filter = get_active_metric_filter()
    if active_filter is not None and scores:
        visible_metrics = set(scores.keys()) & active_filter
    else:
        visible_metrics = set(scores.keys())
    ordered_metric_names = get_metric_order(visible_metrics)
    inject_dashboard_styles()

    # Inline styles for the per-row card layout. Mirrors the .ragas-score-*
    # rules in inject_dashboard_styles but applied directly so the cards
    # still lay out correctly if the global theme didn't load.
    row_style = (
        "display:flex; gap:12px; align-items:stretch; margin:8px 0 4px;"
    )
    base_card_style = (
        "flex:1 1 0; min-width:0; display:flex; flex-direction:column; "
        "justify-content:space-between; "
        "background:rgba(8,10,22,0.92); "
        "border:1px solid rgba(34,211,238,0.22); border-radius:10px; "
        "padding:12px 14px 10px; text-align:center; min-height:96px;"
    )
    name_style = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:0.66rem; letter-spacing:0.08em; text-transform:uppercase; "
        "color:#94a3b8; line-height:1.25; min-height:2.5em; "
        "display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; "
        "overflow:hidden;"
    )
    value_base_style = (
        "font-family:'Orbitron','Rajdhani','Segoe UI',system-ui,sans-serif; "
        "font-size:1.55rem; font-weight:700; letter-spacing:0.04em; "
        "line-height:1.1; margin:6px 0 4px;"
    )
    range_style = (
        "margin:0; font-size:0.68rem; color:#94a3b8; "
        "font-family:'JetBrains Mono','Fira Code','Cascadia Mono',ui-monospace,monospace; "
        "line-height:1.3;"
    )
    good_color = "color:#a3e635; text-shadow:0 0 10px rgba(163,230,53,0.55);"
    low_color = "color:#fde68a; text-shadow:0 0 10px rgba(251,191,36,0.55);"
    good_border = (
        "border-color:#a3e635; "
        "box-shadow:inset 0 0 0 1px rgba(163,230,53,0.25);"
    )
    low_border = (
        "border-color:#fbbf24; "
        "box-shadow:inset 0 0 0 1px rgba(251,191,36,0.35);"
    )

    for stage_name, grouped_metric_names in METRIC_GROUPS:
        stage_metric_names = [
            metric_name for metric_name in grouped_metric_names if metric_name in ordered_metric_names
        ]
        if not stage_metric_names:
            continue

        st.markdown(
            f'<div style="margin:18px 0 10px; font-size:0.78rem; font-weight:800; '
            f'letter-spacing:0.10em; text-transform:uppercase; color:#22d3ee; '
            f'font-family:&apos;Orbitron&apos;,&apos;Rajdhani&apos;,&apos;Segoe UI&apos;,system-ui,sans-serif;">'
            f'{stage_name}</div>',
            unsafe_allow_html=True,
        )

        # Build one equal-height row of cards. CSS flex, all flex:1 1 0.
        card_html = "".join(
            (
                '<div style="{card_style}">'
                '<div style="{name_style}">{name}</div>'
                '<div style="{value_style}">{value:.4f}</div>'
                '<div style="{range_style}">{range_label}</div>'
                '</div>'
            ).format(
                card_style=(
                    base_card_style + (good_border if format_score_class(metric_name, scores[metric_name]) == "ragas-score-good" else low_border)
                ),
                name_style=name_style,
                name=html.escape(metric_name),
                value_style=value_base_style + (
                    good_color if format_score_class(metric_name, scores[metric_name]) == "ragas-score-good" else low_color
                ),
                value=scores[metric_name],
                range_style=range_style,
                range_label=html.escape(str(get_metric_recommendation(metric_name)["label"])),
            )
            for metric_name in stage_metric_names
        )
        st.markdown(f'<div style="{row_style}">{card_html}</div>', unsafe_allow_html=True)

        # For the Rubrics score, surface the matching rubric description
        # directly under the metric (it is the most user-facing metric
        # because it produces a small 1-5 integer rating).
        # Use the ACTIVE rubric so the explanation matches the wording
        # the user picked/edited in the Config tab (not a stale default).
        for metric_name in stage_metric_names:
            if metric_name == "Rubrics score":
                active_rubric = get_active_rubrics()
                rubric_level, rubric_description = get_rubric_level_for_score(
                    scores[metric_name], active_rubric
                )
                if rubric_level is not None:
                    preset_label = st.session_state.get(
                        "rubric_preset_name", DEFAULT_RUBRIC_PRESET
                    )
                    st.markdown(
                        (
                            '<div style="margin-top:10px; padding:10px 12px; border-radius:10px; '
                            'border:1px solid #fbbf24; background:rgba(251,191,36,0.06); '
                            'color:#e2e8f0; font-size:0.85rem; line-height:1.5;">'
                            f'<div style="font-family:&apos;Orbitron&apos;,&apos;Rajdhani&apos;,&apos;Segoe UI&apos;,system-ui,sans-serif; '
                            f'color:#fbbf24; letter-spacing:0.10em; text-transform:uppercase; '
                            f'font-size:0.72rem; margin-bottom:4px;">'
                            f'Level {rubric_level} &middot; {html.escape(preset_label)}</div>'
                            f'<div>{html.escape(rubric_description)}</div>'
                            '</div>'
                        ),
                        unsafe_allow_html=True,
                    )

        # Optional "Why this score?" expanders for any metric that
        # produced a judge-LLM reason. Placed under the row of cards.
        for metric_name in stage_metric_names:
            metric_reason = reasons.get(metric_name)
            if metric_reason:
                with st.expander(f"Why {metric_name}? — judge reasoning", expanded=False):
                    st.write(metric_reason)


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------
def _build_default_config_from_env() -> AppConfig:
    """Build an AppConfig from environment variables only (no Streamlit)."""
    return AppConfig(
        rag_endpoint=os.getenv("RAG_ENDPOINT", "aria://local"),
        llm_api_key=get_required_setting("OPENAI_API_KEY"),
        llm_api_endpoint=get_required_setting("LLM_API_ENDPOINT"),
        llm_model=get_required_setting("LLM_MODEL"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "8192")),
        selected_metrics=AVAILABLE_METRICS.copy(),
        rows=load_default_rows(),
    )


async def _run_cli(rows: list[EvaluationRow], selected_metrics: list[str]) -> list[EvaluationResult]:
    """Run the full evaluation pipeline for a list of rows (no Streamlit)."""
    config = AppConfig(
        rag_endpoint=os.getenv("RAG_ENDPOINT", "aria://local"),
        llm_api_key=get_required_setting("OPENAI_API_KEY"),
        llm_api_endpoint=get_required_setting("LLM_API_ENDPOINT"),
        llm_model=get_required_setting("LLM_MODEL"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "8192")),
        selected_metrics=selected_metrics,
        rows=rows,
    )
    return await evaluate_metrics(config)


def _print_cli_summary(results: list[EvaluationResult]) -> None:
    """Print a compact, table-style summary of the CLI run results."""
    print()
    print("=" * 100)
    print("ARIA CSV RUN SUMMARY")
    print("=" * 100)
    if not results:
        print("No results to display.")
        return

    metric_order = get_metric_order(results[0].scores.keys())
    header = ["#", "Question", "Answer (truncated)"] + metric_order
    print("  ".join(f"{col[:30]:<30}" for col in header))
    print("-" * 100)
    for result in results:
        row_cells = [
            f"{result.row_number:<2}",
            result.question[:30],
            result.response[:30].replace("\n", " "),
        ]
        for metric_name in metric_order:
            score = result.scores.get(metric_name)
            row_cells.append(f"{score:.4f}" if score is not None else "-")
        print("  ".join(f"{cell:<30}" for cell in row_cells))

    print()
    print("Per-metric averages:")
    for metric_name in metric_order:
        scores = [r.scores.get(metric_name) for r in results if r.scores.get(metric_name) is not None]
        if scores:
            print(f"  {metric_name:<40} avg={sum(scores) / len(scores):.4f}  (n={len(scores)})")


def _cli_main(argv: list[str] | None = None) -> int:
    """Run the evaluation headlessly from the command line.

    Honors:
        --data <path>      CSV with question,reference columns.
                           Defaults to ARIA_DATA_FILE env var, then
                           testdata/ARIA_data.csv, then testdata/Test5.json.
        --metrics <list>   Comma-separated metric names to run.
                           Defaults to all available metrics.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Run Test5_allwithUI_aria over a CSV of questions.")
    parser.add_argument("--data", type=Path, default=None, help="Path to CSV with question,reference columns.")
    parser.add_argument(
        "--metrics",
        type=str,
        default=None,
        help="Comma-separated metric names (default: all available).",
    )
    args = parser.parse_args(argv)

    if args.data is not None:
        rows = load_test_rows_from_csv(args.data)
    else:
        rows = load_default_rows()
    if not rows:
        print("No test rows found. Provide --data or check ARIA_DATA_FILE / testdata/ARIA_data.csv.")
        return 1

    if args.metrics:
        selected_metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    else:
        selected_metrics = AVAILABLE_METRICS.copy()

    unknown = [m for m in selected_metrics if m not in AVAILABLE_METRICS]
    if unknown:
        print(f"Unknown metrics: {unknown}")
        print(f"Available: {AVAILABLE_METRICS}")
        return 1

    print(f"Loaded {len(rows)} row(s). Running metrics: {selected_metrics}")

    try:
        results = run_async(_run_cli(rows, selected_metrics))
    except Exception as exc:  # noqa: BLE001
        print(f"Evaluation failed: {type(exc).__name__}: {exc}")
        return 1

    _print_cli_summary(results)
    return 0


def _purge_stale_session_keys() -> None:
    """Drop stale session_state keys from older app versions.

    Keeps the app from blowing up on a stale `rows_editor_<sig>` key
    that contains a `|` (which Streamlit parses as a chained-widget
    delimiter). After the data_editor key was changed to use `-`
    instead, any prior key with a `|` would still be in
    session_state until the browser tab is closed.
    """
    if not hasattr(st, "session_state"):
        return
    for key in list(st.session_state.keys()):
        if key.startswith("rows_editor_") and "|" in key:
            del st.session_state[key]
        # Also drop the corresponding seed signature so the editor
        # re-mounts cleanly with the new key on the next render.
        if key == "rows_data_seed_signature":
            # Re-derive from the current config so the new editor
            # mounts on the new key the first time.
            del st.session_state[key]


def main() -> None:
    """The Streamlit entry point. Sets up the page, then renders the
    three tabs: Config, Results, and Metric."""
    st.set_page_config(page_title="RAG Metrics UI", layout="wide")
    # Purge any session_state keys left over from older versions of
    # the app (e.g. rows_editor_* keys containing a `|`, which Streamlit
    # rejects on the next rerun).
    _purge_stale_session_keys()
    # Inject the cyberpunk theme globally so it covers the page chrome
    # (tabs, sidebar, buttons, data editor) — not just the per-tab HTML.
    inject_dashboard_styles()
    st.title("RAG Metrics Evaluation")
    st.caption(
        "Configure one or more rows, run the selected no-embedding metrics, and inspect the full result set."
    )

    # Sidebar: LLM provider selector. Picking a provider writes the
    # pre-filled endpoint + model into session_state so the Config form
    # starts with the right values. The API key is always read from
    # 1.env (never shown in the UI).
    with st.sidebar:
        render_provider_sidebar()

    default_config = build_default_config()
    config_tab, results_tab, analytics_tab, metric_tab = st.tabs(
        ["Config", "Results", "Analytics", "Metric"]
    )

    with config_tab:
        render_config_tab(default_config)

    with results_tab:
        render_results_tab()

    with analytics_tab:
        render_analytics_tab()

    with metric_tab:
        render_metric_tab()


def render_provider_sidebar() -> None:
    """Render the LLM-provider picker in the Streamlit sidebar.

    Lets the user switch between Ollama / Baseten / OpenAI / Azure /
    Custom without editing 1.env. The chosen provider writes its
    endpoint + model into `st.session_state["provider_endpoint"]` and
    `st.session_state["provider_model"]`, which the Config form reads
    as its starting values. The API key is read from the env (never
    typed in the UI) and a small "key detected" badge confirms 1.env
    is loaded.
    """
    st.markdown(
        "### LLM Provider",
        help="Switch the judge LLM between Ollama (local), Baseten, OpenAI, Azure, or Custom.",
    )

    preset_names = list(LLM_PROVIDER_PRESETS.keys())
    # Seed the dropdown with the first run, then preserve the user's pick.
    if "provider_name" not in st.session_state:
        st.session_state["provider_name"] = preset_names[0]
    if "provider_endpoint" not in st.session_state:
        st.session_state["provider_endpoint"] = os.getenv("LLM_API_ENDPOINT", "")
    if "provider_model" not in st.session_state:
        st.session_state["provider_model"] = os.getenv("LLM_MODEL", "")

    current_index = (
        preset_names.index(st.session_state["provider_name"])
        if st.session_state["provider_name"] in preset_names
        else 0
    )
    selected = st.selectbox(
        "Provider",
        options=preset_names,
        index=current_index,
        key="provider_select",
        help=LLM_PROVIDER_PRESETS[preset_names[current_index]]["help"],
    )
    if selected != st.session_state.get("provider_name"):
        st.session_state["provider_name"] = selected
        preset = LLM_PROVIDER_PRESETS[selected]
        # Only auto-fill when the user hasn't customized the field for
        # this provider; for "Custom" we leave whatever they typed.
        st.session_state["provider_endpoint"] = preset["endpoint"]
        st.session_state["provider_model"] = preset["model"]
        st.rerun()

    st.caption(LLM_PROVIDER_PRESETS[selected]["help"])

    # API key status: we never display the key itself, just whether one
    # was loaded from the env. This is the only signal the user needs
    # to know their 1.env is wired up correctly.
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        masked = f"{api_key[:4]}{'*' * max(0, len(api_key) - 8)}{api_key[-4:]}" if len(api_key) > 8 else "****"
        st.success(f"API key loaded: `{masked}`")
    else:
        st.error("No OPENAI_API_KEY in 1.env — set it before running metrics.")

    st.markdown("---")
    st.markdown(
        "**Edit the endpoint/model in the Config tab** to override these "
        "defaults. The API key is always read from `1.env`."
    )


if __name__ == "__main__":
    import sys as _sys

    # Detect whether we are running under `streamlit run ...` or as a CLI.
    # The previous check only looked at sys.argv[0] and failed because
    # `streamlit run Test5_allwithUI_aria.py` puts the script path in
    # argv[0] (not the word "streamlit"), so the CLI runner would always
    # fire and the UI would never render. Use Streamlit's own runtime
    # context as the source of truth; fall back to CLI flags.
    _launched_by_streamlit = False
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            _launched_by_streamlit = True
    except Exception:
        pass

    if not _launched_by_streamlit:
        # Also accept an explicit --ui flag so users can force the UI from a CLI.
        if any(str(a) == "--ui" for a in _sys.argv[1:]):
            _launched_by_streamlit = True
        # And treat the absence of CLI-only flags as a UI launch.
        elif not any(
            str(a) in {"--data", "--metrics", "--help", "-h"}
            for a in _sys.argv[1:]
        ):
            _launched_by_streamlit = True

    if _launched_by_streamlit:
        main()
    else:
        raise SystemExit(_cli_main())
