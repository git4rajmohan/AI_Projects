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
# html        : safely escape text before showing it on the webpage
# json        : parse JSON replies from the LLM
# os, sys     : read environment variables and tweak Python's import system
# re          : simple text cleanup with regular expressions
# types       : lets us create fake/stub modules on the fly
# dataclasses : a tidy way to define simple data "records" (like rows)
# pathlib     : handle file paths in a clean, cross-platform way
# typing.Any  : a type hint meaning "anything goes"
import asyncio
import html
import json
import os
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ----- Third-party libraries -----
# pandas      : used to build editable tables in the UI
# streamlit   : the web UI framework that turns Python into a webpage
# dotenv      : reads settings from the "1.env" file (API keys, URLs, etc.)
# openai      : the official OpenAI client (works with any compatible API)
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import AsyncOpenAI

# ----- Our own helpers (defined in utils.py) -----
# get_llm_response : calls our RAG endpoint with a question and gets back
#                    {"answer": "...", "retrieved_docs": [...]}
# load_test_data   : reads the default test rows from testdata/Test5.json
from utils import get_llm_response, load_test_data


# Path to the file that holds secrets and settings (API key, base URLs, etc.)
ENV_FILE = Path(__file__).with_name("1.env")

# These are URL endings we want to strip off if a user pastes a full
# chat-completions URL into the "base URL" field, so the OpenAI client
# can build correct request URLs underneath.
OPENAI_COMPLETION_SUFFIXES = ("/chat/completions", "/completions")

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

# Rubric used by the "Rubrics score" metric. Mirrors the rubric in Test7.py.
# Each key is a score level (1-5) and the value describes what that score means.
# The judge LLM picks the level that best matches the response.
RUBRICS = {
    "score1_description": "The response is incorrect, irrelevant, or does not align with the ground truth.",
    "score2_description": "The response partially matches the ground truth but includes significant errors, omissions, or irrelevant information.",
    "score3_description": "The response generally aligns with the ground truth but may lack detail, clarity, or have minor inaccuracies.",
    "score4_description": "The response is mostly accurate and aligns well with the ground truth, with only minor issues or missing details.",
    "score5_description": "The response is fully accurate, aligns completely with the ground truth, and is clear and detailed.",
}


def get_rubric_level_for_score(score: float) -> tuple[int | None, str]:
    """Given a numeric Rubrics score, return (level, description) for the
    matching level in the RUBRICS dict. Levels are 1-5. If the score is
    outside the 1-5 range, returns (None, "") so callers can no-op."""
    try:
        level = int(round(float(score)))
    except (TypeError, ValueError):
        return None, ""
    key = f"score{level}_description"
    if level < 1 or level > 5 or key not in RUBRICS:
        return None, ""
    return level, RUBRICS[key]

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
    """Load the default test questions/references from testdata/Test5.json.
    If that file is empty, fall back to single-row values from env vars."""
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
    """Ask the RAG system the question and package the result into a
    RAGAS "SingleTurnSample" — the data shape RAGAS expects for scoring."""
    response_payload = get_llm_response({"question": row.question})
    return SingleTurnSample(
        user_input=row.question,
        response=normalize_text(response_payload.get("answer", "")),
        retrieved_contexts=[
            normalize_text(document.get("page_content", ""))
            for document in response_payload.get("retrieved_docs", [])
            if normalize_text(document.get("page_content", ""))
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
            RubricsScoreWithReference(rubrics=RUBRICS, llm=llm_wrapper),
            {
                "user_input": sample.user_input,
                "response": sample.response,
                "reference": sample.reference,
            },
        ),
    }


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
    It's hand-built as HTML/CSS (not a normal Streamlit table) so it can
    show formatted cells and look nice."""
    inject_dashboard_styles()
    st.markdown("### Metric Guide")
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
    row_cells: list[str] = []
    for row in guide_rows:
        row_cells.extend(
            [
                f'<div class="ragas-guide-cell ragas-guide-cell-metric">{html.escape(row["Metric"])}</div>',
                f'<div class="ragas-guide-cell ragas-guide-cell-stage">{html.escape(row["RAG Stage"])}</div>',
                f'<div class="ragas-guide-cell ragas-guide-cell-range">{html.escape(row["Recommended Range"])}</div>',
                f'<div class="ragas-guide-cell">{html.escape(row["What it is"])}</div>',
                f'<div class="ragas-guide-cell">{html.escape(row["Inputs"])}</div>',
                f'<div class="ragas-guide-cell">{html.escape(row["How it is calculated"])}</div>',
                f'<div class="ragas-guide-cell">{html.escape(row["Low vs High"])}</div>',
            ]
        )

    st.markdown(
        (
            '<div class="ragas-guide-table">'
            '<div class="ragas-guide-scroll">'
            '<div class="ragas-guide-grid">'
            + "".join(
                [f'<div class="ragas-guide-header">{html.escape(header)}</div>' for header in header_cells]
            )
            + "".join(row_cells)
            + '</div></div></div>'
        ),
        unsafe_allow_html=True,
    )


def inject_dashboard_grid_columns(metric_names: list[str], column_track: str) -> None:
    """Write a small inline <style> that overrides the metric-column track on
    the next .ragas-dashboard-grid element. This keeps the table aligned
    regardless of how many metrics are selected (the default in
    inject_dashboard_styles assumes 6 metric columns)."""
    st.markdown(
        f"""
        <style>
        .ragas-dashboard-grid {{
            --ragas-metric-columns: {column_track};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_dashboard_styles() -> None:
    st.markdown(
        """
        <style>
        .ragas-dashboard {
            border: 1px solid rgba(250, 204, 21, 0.25);
            border-radius: 16px;
            background: rgba(10, 10, 10, 0.82);
            overflow: hidden;
        }

        .ragas-guide-table {
            border: 1px solid rgba(250, 204, 21, 0.25);
            border-radius: 16px;
            background: rgba(10, 10, 10, 0.82);
            overflow: hidden;
            margin-top: 10px;
        }

        .ragas-guide-scroll {
            overflow-x: auto;
        }

        .ragas-guide-grid {
            display: grid;
            grid-template-columns: minmax(180px, 0.9fr) minmax(160px, 0.75fr) minmax(150px, 0.75fr) minmax(320px, 1.15fr) minmax(240px, 0.9fr) minmax(360px, 1.2fr) minmax(340px, 1.15fr);
            min-width: 2050px;
        }

        .ragas-guide-header {
            padding: 16px 16px;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
            border-bottom: 1px solid rgba(250, 204, 21, 0.2);
            background: rgba(255, 255, 255, 0.02);
            font-size: 0.85rem;
            font-weight: 700;
            color: #f5f5f5;
        }

        .ragas-guide-cell {
            min-height: 108px;
            padding: 18px 16px;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            background: rgba(255, 255, 255, 0.01);
            color: #e5e7eb;
            font-size: 0.92rem;
            line-height: 1.65;
            white-space: normal;
            word-break: break-word;
        }

        .ragas-guide-cell-metric {
            font-weight: 700;
            color: #f9fafb;
        }

        .ragas-guide-cell-stage {
            color: #fde68a;
            font-weight: 700;
        }

        .ragas-guide-cell-range {
            color: #bbf7d0;
            font-weight: 700;
        }

        .ragas-dashboard-scroll {
            overflow-x: auto;
        }

        .ragas-dashboard-grid {
            display: grid;
            grid-template-columns: 72px minmax(220px, 1.2fr) minmax(320px, 1.3fr) minmax(260px, 1.1fr) minmax(260px, 1.1fr) var(--ragas-metric-columns, repeat(6, minmax(130px, 0.55fr)));
            min-width: 1800px;
        }

        .ragas-header-cell {
            padding: 14px 16px;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
            border-bottom: 1px solid rgba(250, 204, 21, 0.2);
            background: rgba(255, 255, 255, 0.02);
            font-size: 0.86rem;
            font-weight: 700;
            color: #f5f5f5;
            position: sticky;
            top: 0;
            z-index: 1;
        }

        .ragas-header-title {
            display: block;
        }

        .ragas-header-range {
            display: block;
            margin-top: 6px;
            font-size: 0.7rem;
            font-weight: 600;
            color: #fcd34d;
            line-height: 1.35;
        }

        .ragas-row-cell {
            padding: 14px 16px;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            background: rgba(255, 255, 255, 0.01);
            color: #e5e7eb;
            font-size: 0.9rem;
        }

        .ragas-row-number {
            display: flex;
            align-items: center;
            justify-content: center;
            color: #d1d5db;
            font-weight: 600;
        }

        .ragas-scroll-box {
            max-height: 160px;
            min-height: 110px;
            overflow-y: auto;
            line-height: 1.5;
            padding-right: 6px;
            scrollbar-width: thin;
        }

        .ragas-scroll-box::-webkit-scrollbar {
            width: 8px;
        }

        .ragas-scroll-box::-webkit-scrollbar-thumb {
            background: rgba(250, 204, 21, 0.45);
            border-radius: 999px;
        }

        .ragas-scroll-box::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.04);
            border-radius: 999px;
        }

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
            background: rgba(250, 204, 21, 0.12);
            color: #fde68a;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            text-transform: uppercase;
        }

        .ragas-score-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: 44px;
            border-radius: 12px;
            background: rgba(17, 24, 39, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #f9fafb;
            font-weight: 700;
            font-size: 1rem;
        }

        .ragas-score-good {
            box-shadow: inset 0 0 0 1px rgba(74, 222, 128, 0.25);
            color: #bbf7d0;
        }

        .ragas-score-medium {
            box-shadow: inset 0 0 0 1px rgba(250, 204, 21, 0.25);
            color: #fde68a;
        }

        .ragas-score-low {
            box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.25);
            color: #fecaca;
        }

        .ragas-stage-label {
            margin: 18px 0 10px;
            font-size: 0.8rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #facc15;
        }

        .ragas-score-range {
            margin-top: 6px;
            font-size: 0.75rem;
            color: #fcd34d;
            line-height: 1.4;
        }

        .ragas-rubric-explanation {
            margin-top: 8px;
            padding: 8px 10px;
            border-radius: 8px;
            background: rgba(250, 204, 21, 0.08);
            border: 1px solid rgba(250, 204, 21, 0.18);
            text-align: left;
            color: #f5f5f5;
            font-size: 0.78rem;
            line-height: 1.45;
        }

        .ragas-rubric-level {
            font-weight: 700;
            color: #fde68a;
            margin-bottom: 2px;
            font-size: 0.72rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .ragas-rubric-text {
            color: #e5e7eb;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_score_class(metric_name: str, score: float) -> str:
    """Decide which color a score pill should use:
       - green  ('good')    if the score meets the recommended minimum
       - yellow ('medium')  if it's within 0.15 of the minimum
       - red    ('low')     otherwise
    """
    recommendation = get_metric_recommendation(metric_name)
    recommended_min = float(recommendation["min"])
    warning_floor = max(0.0, recommended_min - 0.15)
    if score >= recommended_min:
        return "ragas-score-good"
    if score >= warning_floor:
        return "ragas-score-medium"
    return "ragas-score-low"


def render_dashboard_table(results: list[EvaluationResult]) -> None:
    """Build the main score dashboard as HTML/CSS: one column per metric,
    one row per question, with the score rendered as a colored 'pill'.
    The grid columns are built dynamically so adding/removing a metric
    does not break alignment."""
    inject_dashboard_styles()
    metric_names = get_metric_order(results[0].scores.keys()) if results else []
    metric_column_track = " ".join(
        ["minmax(120px, 0.55fr)"] * len(metric_names)
    ) if metric_names else "0px"
    inject_dashboard_grid_columns(metric_names, metric_column_track)

    header_cells = [
        '<div class="ragas-header-cell">#</div>',
        '<div class="ragas-header-cell">User Input</div>',
        '<div class="ragas-header-cell">Retrieved Contexts</div>',
        '<div class="ragas-header-cell">Response</div>',
        '<div class="ragas-header-cell">Reference</div>',
    ]
    header_cells.extend(
        [
            (
                '<div class="ragas-header-cell">'
                f'<span class="ragas-header-title">{html.escape(metric_name)}</span>'
                f'<span class="ragas-header-range">{html.escape(str(get_metric_recommendation(metric_name)["label"]))}</span>'
                '</div>'
            )
            for metric_name in metric_names
        ]
    )

    row_cells: list[str] = []
    for result in results:
        context_html = "".join(
            [
                (
                    '<div class="ragas-context-item">'
                    f'<div class="ragas-context-label">Context {index}</div>'
                    f'<div>{html.escape(context)}</div>'
                    '</div>'
                )
                for index, context in enumerate(result.retrieved_contexts, start=1)
            ]
        ) or '<div class="ragas-context-item"><div>No contexts returned.</div></div>'

        row_cells.extend(
            [
                f'<div class="ragas-row-cell ragas-row-number">{result.row_number}</div>',
                (
                    '<div class="ragas-row-cell">'
                    f'<div class="ragas-scroll-box">{html.escape(result.question)}</div>'
                    '</div>'
                ),
                (
                    '<div class="ragas-row-cell">'
                    f'<div class="ragas-scroll-box">{context_html}</div>'
                    '</div>'
                ),
                (
                    '<div class="ragas-row-cell">'
                    f'<div class="ragas-scroll-box">{html.escape(result.response)}</div>'
                    '</div>'
                ),
                (
                    '<div class="ragas-row-cell">'
                    f'<div class="ragas-scroll-box">{html.escape(result.reference)}</div>'
                    '</div>'
                ),
            ]
        )

        for metric_name in metric_names:
            score = result.scores[metric_name]
            score_cell_html = (
                f'<div class="ragas-score-pill {format_score_class(metric_name, score)}">{score:.4f}</div>'
            )
            # For the Rubrics score (a 1-5 integer rating), show the matching
            # rubric description from the RUBRICS dict so the user can see
            # *what* that level means without opening row details.
            rubric_explanation_html = ""
            if metric_name == "Rubrics score":
                rubric_level, rubric_description = get_rubric_level_for_score(score)
                if rubric_level is not None:
                    rubric_explanation_html = (
                        f'<div class="ragas-rubric-explanation">'
                        f'<div class="ragas-rubric-level">Level {rubric_level}</div>'
                        f'<div class="ragas-rubric-text">{html.escape(rubric_description)}</div>'
                        '</div>'
                    )
            row_cells.append(
                (
                    '<div class="ragas-row-cell">'
                    f'{score_cell_html}{rubric_explanation_html}'
                    '</div>'
                )
            )

    st.markdown(
        (
            '<div class="ragas-dashboard">'
            '<div class="ragas-dashboard-scroll">'
            '<div class="ragas-dashboard-grid">'
            + "".join(header_cells)
            + "".join(row_cells)
            + '</div></div></div>'
        ),
        unsafe_allow_html=True,
    )


def render_results_tab() -> None:
    """Render the 'Results' tab: dashboard, summary table, and per-row details.
    If no evaluation has been run yet, just show a helpful message."""
    st.subheader("Evaluation Results")
    results: list[EvaluationResult] = st.session_state.get("evaluation_results", [])

    if not results:
        st.info("Run an evaluation from the Config tab to see results here.")
        return

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
    st.subheader("Configuration")
    with st.form("evaluation_form"):
        left_column, right_column = st.columns(2)

        with left_column:
            llm_model = st.text_input("LLM Model", value=active_config.llm_model)
            llm_temperature = st.number_input(
                "LLM Temperature",
                min_value=0.0,
                max_value=2.0,
                value=float(active_config.llm_temperature),
                step=0.1,
            )
            llm_max_tokens = st.number_input(
                "LLM Max Tokens",
                min_value=512,
                max_value=32768,
                value=int(active_config.llm_max_tokens),
                step=512,
            )

        with right_column:
            llm_api_endpoint = st.text_input(
                "LLM API Endpoint",
                value=active_config.llm_api_endpoint,
            )
            selected_metrics = st.multiselect(
                "Metrics to run",
                options=AVAILABLE_METRICS,
                default=active_config.selected_metrics,
            )
            st.caption(
                "Step 1 fetches the RAG response and retrieved contexts for review. Step 2 runs metrics only after you inspect or edit that data."
            )

        edited_rows = st.data_editor(
            build_rows_dataframe(active_config.rows),
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "Question": st.column_config.TextColumn(required=True, width="large"),
                "Ground Truth": st.column_config.TextColumn(required=True, width="large"),
            },
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
    """Render one row of 'metric cards' per RAG stage (Retrieval / Augmentation
    / Generation). Each card shows the score and its recommended range.
    If a metric produced a judge-LLM reason, it is shown in smaller text
    below the card so the user can interpret non-numeric metrics like
    Rubrics score (1-5)."""
    reasons = reasons or {}
    ordered_metric_names = get_metric_order(scores.keys())
    for stage_name, grouped_metric_names in METRIC_GROUPS:
        stage_metric_names = [
            metric_name for metric_name in grouped_metric_names if metric_name in ordered_metric_names
        ]
        if not stage_metric_names:
            continue

        st.markdown(f'<div class="ragas-stage-label">{stage_name}</div>', unsafe_allow_html=True)
        columns = st.columns(len(stage_metric_names))
        for column, metric_name in zip(columns, stage_metric_names):
            recommendation_label = str(get_metric_recommendation(metric_name)["label"])
            column.metric(metric_name, f"{scores[metric_name]:.4f}")
            column.markdown(
                f'<div class="ragas-score-range">{html.escape(recommendation_label)}</div>',
                unsafe_allow_html=True,
            )
            # For the Rubrics score, surface the matching rubric description
            # directly under the metric (it is the most user-facing metric
            # because it produces a small 1-5 integer rating).
            if metric_name == "Rubrics score":
                rubric_level, rubric_description = get_rubric_level_for_score(scores[metric_name])
                if rubric_level is not None:
                    column.markdown(
                        (
                            '<div class="ragas-rubric-explanation">'
                            f'<div class="ragas-rubric-level">Level {rubric_level}</div>'
                            f'<div class="ragas-rubric-text">{html.escape(rubric_description)}</div>'
                            '</div>'
                        ),
                        unsafe_allow_html=True,
                    )
            metric_reason = reasons.get(metric_name)
            if metric_reason:
                with column.expander("Why this score?", expanded=False):
                    st.write(metric_reason)


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """The Streamlit entry point. Sets up the page, then renders the
    three tabs: Config, Results, and Metric."""
    st.set_page_config(page_title="RAG Metrics UI", layout="wide")
    st.title("RAG Metrics Evaluation")
    st.caption(
        "Configure one or more rows, run the selected no-embedding metrics, and inspect the full result set."
    )

    default_config = build_default_config()
    config_tab, results_tab, metric_tab = st.tabs(["Config", "Results", "Metric"])

    with config_tab:
        render_config_tab(default_config)

    with results_tab:
        render_results_tab()

    with metric_tab:
        render_metric_tab()


if __name__ == "__main__":
    main()
