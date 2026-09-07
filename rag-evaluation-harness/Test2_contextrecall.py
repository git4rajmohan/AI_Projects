# Use asyncio so the file can run as both a normal script and a pytest async test.
import asyncio
# Use json to normalize structured responses returned by the Baseten model.
import json
# Use os to read environment variables from the current process.
import os
# Use sys to register a small compatibility shim before importing ragas.
import sys
# Use types to create the compatibility module object dynamically.
import types
# Use dataclass to group top-level configuration into one typed object.
from dataclasses import dataclass
# Use Path to locate the local 1.env file next to this script.
from pathlib import Path
# Use Any for flexible response typing when patching the OpenAI-compatible client.
from typing import Any

# Use pytest so the same logic can run as an automated test.
import pytest
# Use requests for the synchronous RAG endpoint call.
import requests
# Use dotenv to load the local 1.env file into the process environment.
from dotenv import load_dotenv
# Use AsyncOpenAI because ragas scoring runs asynchronously.
from openai import AsyncOpenAI


# Point to the project-local environment file.
ENV_FILE = Path(__file__).with_name("1.env")
# Keep the default question configurable at the top of the file.
DEFAULT_QUESTION = "How many articles are there in the Selenium webdriver python course?"
# Keep the default passing threshold configurable at the top of the file.
DEFAULT_SCORE_THRESHOLD = 0.7
# Keep the supported OpenAI-compatible completion suffixes configurable at the top of the file.
OPENAI_COMPLETION_SUFFIXES = ("/chat/completions", "/completions")


# Load settings from 1.env and force them to override any older shell variables.
load_dotenv(ENV_FILE, override=True)


def ensure_vertexai_compatibility() -> None:
    """Create a lightweight shim for an optional langchain module that ragas still imports."""

    if "langchain_community.chat_models.vertexai" in sys.modules:
        return

    vertexai_module = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:
        pass

    vertexai_module.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = vertexai_module


# Apply the compatibility shim before importing ragas.
ensure_vertexai_compatibility()


# Import the ragas sample container used by the metric call.
from ragas import SingleTurnSample
# Import the modern ragas LLM factory used by collection metrics.
from ragas.llms import llm_factory
# Import the supported modern context recall metric.
from ragas.metrics.collections import ContextRecall


@dataclass(frozen=True)
class AppConfig:
    """Store all runtime configuration in one place."""

    llm_api_key: str
    llm_api_endpoint: str
    llm_base_url: str
    llm_model: str
    llm_temperature: float
    rag_endpoint: str
    question: str
    reference_answer: str
    score_threshold: float = DEFAULT_SCORE_THRESHOLD


def get_required_setting(name: str) -> str:
    """Read a required environment value and fail early if it is missing."""

    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def normalize_openai_base_url(endpoint: str) -> str:
    """Convert a full completions endpoint into the base URL expected by the OpenAI client."""

    normalized_endpoint = endpoint.rstrip("/")
    for suffix in OPENAI_COMPLETION_SUFFIXES:
        if normalized_endpoint.endswith(suffix):
            return normalized_endpoint[: -len(suffix)]
    return normalized_endpoint


def load_config() -> AppConfig:
    """Build the application configuration from top-level environment settings."""

    llm_api_endpoint = get_required_setting("LLM_API_ENDPOINT")
    return AppConfig(
        llm_api_key=get_required_setting("OPENAI_API_KEY"),
        llm_api_endpoint=llm_api_endpoint,
        llm_base_url=normalize_openai_base_url(llm_api_endpoint),
        llm_model=get_required_setting("LLM_MODEL"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        rag_endpoint=get_required_setting("RAG_ENDPOINT"),
        question=os.getenv("QUESTION", DEFAULT_QUESTION),
        reference_answer=os.getenv("REFERENCE_ANSWER", "").strip(),
    )


# Build the shared configuration once at import time.
CONFIG = load_config()


def normalize_response_content(response: Any) -> Any:
    """Move Baseten structured output into message.content so ragas can parse it."""

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


def patch_async_client_for_baseten(client: AsyncOpenAI) -> AsyncOpenAI:
    """Patch the async client so Baseten responses look like standard OpenAI responses."""

    original_create = client.chat.completions.create

    async def create_with_normalized_content(*args, **kwargs):
        response = await original_create(*args, **kwargs)
        return normalize_response_content(response)

    client.chat.completions.create = create_with_normalized_content
    return client


def build_async_client(config: AppConfig) -> AsyncOpenAI:
    """Create and patch the OpenAI-compatible async client."""

    client = AsyncOpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )
    return patch_async_client_for_baseten(client)


def build_metric(config: AppConfig) -> ContextRecall:
    """Create the ragas context recall metric for the configured model."""

    client = build_async_client(config)
    llm = llm_factory(
        config.llm_model,
        client=client,
        temperature=config.llm_temperature,
    )
    return ContextRecall(llm=llm)


def fetch_rag_response(config: AppConfig) -> dict[str, Any]:
    """Call the external RAG endpoint and return its JSON payload."""

    response = requests.post(
        config.rag_endpoint,
        json={
            "question": config.question,
            "chat_history": [],
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def build_sample(config: AppConfig, rag_response: dict[str, Any]) -> SingleTurnSample:
    """Convert the RAG response into the ragas sample object used for scoring."""

    retrieved_docs = rag_response["retrieved_docs"]
    retrieved_contexts = [document["page_content"] for document in retrieved_docs]
    reference_answer = config.reference_answer or rag_response["answer"]
    return SingleTurnSample(
        user_input=config.question,
        retrieved_contexts=retrieved_contexts,
        reference=reference_answer,
    )


async def calculate_context_recall(
    config: AppConfig,
    metric: ContextRecall,
    sample: SingleTurnSample,
) -> float:
    """Run the ragas metric and return only the numeric score value."""

    score = await metric.ascore(
        user_input=sample.user_input,
        retrieved_contexts=sample.retrieved_contexts,
        reference=sample.reference,
    )
    return score.value


async def run_context_recall(config: AppConfig = CONFIG) -> float:
    """Execute the full RAG fetch plus context recall scoring workflow."""

    os.environ["OPENAI_API_KEY"] = config.llm_api_key
    metric = build_metric(config)
    rag_response = fetch_rag_response(config)
    print(f"Query used: {config.question}")
    print(rag_response)
    sample = build_sample(config, rag_response)
    print(f"No of context retrieved: {len(sample.retrieved_contexts)}")

    try:
        score = await calculate_context_recall(config, metric, sample)
    except Exception as exc:
        print(
            "LLM scoring failed. Check LLM_API_ENDPOINT, LLM_MODEL, and the API key configured in 1.env."
        )
        print(f"Configured endpoint: {config.llm_base_url}")
        print(f"Configured model: {config.llm_model}")
        raise exc

    print(score)
    return score


@pytest.mark.asyncio
async def test_context_recall() -> None:
    """Pytest entry point that validates the score stays above the configured threshold."""

    score = await run_context_recall()
    assert score > CONFIG.score_threshold


def main() -> int:
    """Run the script directly and return a shell-friendly exit code."""

    try:
        asyncio.run(run_context_recall())
    except Exception:
        print("No score produced.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
