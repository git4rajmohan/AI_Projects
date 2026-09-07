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
DEFAULT_SCORE_THRESHOLD = 0.8
# Keep the supported OpenAI-compatible completion suffixes configurable at the top of the file.
OPENAI_COMPLETION_SUFFIXES = ("/chat/completions", "/completions")


# Load settings from 1.env and force them to override any older shell variables.
load_dotenv(ENV_FILE, override=True)


def ensure_vertexai_compatibility() -> None:
    """Create a lightweight shim for an optional langchain module that ragas still imports."""

    # Skip the shim if the module already exists in the current interpreter.
    if "langchain_community.chat_models.vertexai" in sys.modules:
        return

    # Create a temporary in-memory module with the expected import path.
    vertexai_module = types.ModuleType("langchain_community.chat_models.vertexai")

    # Define the placeholder class that ragas expects to import.
    class ChatVertexAI:
        pass

    # Attach the placeholder class to the temporary module.
    vertexai_module.ChatVertexAI = ChatVertexAI
    # Register the temporary module so later imports can resolve it.
    sys.modules["langchain_community.chat_models.vertexai"] = vertexai_module


# Apply the compatibility shim before importing ragas.
ensure_vertexai_compatibility()


# Import the ragas sample container used by the metric call.
from ragas import SingleTurnSample
# Import the modern ragas LLM factory used by collection metrics.
from ragas.llms import llm_factory
# Import the supported modern context precision metric.
from ragas.metrics.collections import ContextPrecisionWithoutReference


@dataclass(frozen=True)
class AppConfig:
    """Store all runtime configuration in one place."""

    # Store the LLM API key from 1.env.
    llm_api_key: str
    # Store the raw endpoint from 1.env.
    llm_api_endpoint: str
    # Store the normalized base URL expected by the OpenAI-compatible client.
    llm_base_url: str
    # Store the selected cloud model name.
    llm_model: str
    # Store the model temperature as a float.
    llm_temperature: float
    # Store the RAG application endpoint.
    rag_endpoint: str
    # Store the question sent to the RAG endpoint.
    question: str
    # Store the score threshold used by the test assertion.
    score_threshold: float = DEFAULT_SCORE_THRESHOLD


def get_required_setting(name: str) -> str:
    """Read a required environment value and fail early if it is missing."""

    # Read the environment variable from the active process.
    value = os.getenv(name)
    # Raise a clear error if the value is empty or missing.
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    # Return the validated non-empty value.
    return value


def normalize_openai_base_url(endpoint: str) -> str:
    """Convert a full completions endpoint into the base URL expected by the OpenAI client."""

    # Remove a trailing slash so suffix matching is predictable.
    normalized_endpoint = endpoint.rstrip("/")
    # Walk through the known completion suffixes that should be stripped.
    for suffix in OPENAI_COMPLETION_SUFFIXES:
        # Strip the suffix if the provided endpoint includes it.
        if normalized_endpoint.endswith(suffix):
            return normalized_endpoint[: -len(suffix)]
    # Return the input unchanged when it is already a base URL.
    return normalized_endpoint


def load_config() -> AppConfig:
    """Build the application configuration from top-level environment settings."""

    # Read the raw LLM endpoint from 1.env.
    llm_api_endpoint = get_required_setting("LLM_API_ENDPOINT")
    # Create and return the immutable runtime config object.
    return AppConfig(
        llm_api_key=get_required_setting("OPENAI_API_KEY"),
        llm_api_endpoint=llm_api_endpoint,
        llm_base_url=normalize_openai_base_url(llm_api_endpoint),
        llm_model=get_required_setting("LLM_MODEL"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        rag_endpoint=get_required_setting("RAG_ENDPOINT"),
        question=os.getenv("QUESTION", DEFAULT_QUESTION),
    )


# Build the shared configuration once at import time.
CONFIG = load_config()


def normalize_response_content(response: Any) -> Any:
    """Move Baseten structured output into message.content so ragas can parse it."""

    # Loop through every choice returned by the model response.
    for choice in getattr(response, "choices", []):
        # Read the assistant message from the current choice.
        message = getattr(choice, "message", None)
        # Skip choices that do not include a message object.
        if message is None:
            continue

        # Read the normal content field expected by OpenAI-compatible clients.
        content = getattr(message, "content", None)
        # Read the Baseten-specific reasoning field used by this model.
        reasoning_content = getattr(message, "reasoning_content", None)

        # Fall back to reasoning_content when the normal content field is empty.
        if not content and reasoning_content:
            content = reasoning_content.strip()

        # Skip empty responses after the fallback check.
        if not content:
            continue

        # Try to parse the returned text as JSON because ragas expects structured output.
        try:
            parsed = json.loads(content)
        # Preserve plain text when the response is not JSON.
        except json.JSONDecodeError:
            message.content = content
            continue

        # Convert a one-item JSON list into a plain JSON object string for ragas.
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            message.content = json.dumps(parsed[0])
        # Keep plain JSON objects as JSON strings in message.content.
        elif isinstance(parsed, dict):
            message.content = json.dumps(parsed)
        # Preserve any other JSON shape as-is.
        else:
            message.content = content

    # Return the patched response object.
    return response


def patch_async_client_for_baseten(client: AsyncOpenAI) -> AsyncOpenAI:
    """Patch the async client so Baseten responses look like standard OpenAI responses."""

    # Keep the original create method so the wrapper can delegate to it.
    original_create = client.chat.completions.create

    # Wrap the original create method with response normalization.
    async def create_with_normalized_content(*args, **kwargs):
        # Execute the original request first.
        response = await original_create(*args, **kwargs)
        # Normalize the response content before returning it.
        return normalize_response_content(response)

    # Replace the client's create method with the wrapper.
    client.chat.completions.create = create_with_normalized_content
    # Return the patched client for fluent usage.
    return client


def build_async_client(config: AppConfig) -> AsyncOpenAI:
    """Create and patch the OpenAI-compatible async client."""

    # Build the OpenAI-compatible async client from the top-level config.
    client = AsyncOpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )
    # Patch the client so Baseten structured output is normalized for ragas.
    return patch_async_client_for_baseten(client)


def build_metric(config: AppConfig) -> ContextPrecisionWithoutReference:
    """Create the ragas context precision metric for the configured model."""

    # Create the async OpenAI-compatible client.
    client = build_async_client(config)
    # Build the ragas LLM wrapper from the configured model and temperature.
    llm = llm_factory(
        config.llm_model,
        client=client,
        temperature=config.llm_temperature,
    )
    # Return the configured context precision metric instance.
    return ContextPrecisionWithoutReference(llm=llm)


def fetch_rag_response(config: AppConfig) -> dict[str, Any]:
    """Call the external RAG endpoint and return its JSON payload."""

    # Send the question to the configured RAG endpoint.
    response = requests.post(
        config.rag_endpoint,
        json={
            "question": config.question,
            "chat_history": [],
        },
        timeout=120,
    )
    # Raise immediately if the RAG endpoint returns an HTTP error.
    response.raise_for_status()
    # Convert the HTTP response body into a Python dictionary.
    return response.json()


def build_sample(config: AppConfig, rag_response: dict[str, Any]) -> SingleTurnSample:
    """Convert the RAG response into the ragas sample object used for scoring."""

    # Read the retrieved document list from the RAG payload.
    retrieved_docs = rag_response["retrieved_docs"]
    # Use every context returned by the RAG system for the metric input.
    retrieved_contexts = [document["page_content"] for document in retrieved_docs]
    # Build and return the ragas single-turn sample.
    return SingleTurnSample(
        user_input=config.question,
        response=rag_response["answer"],
        retrieved_contexts=retrieved_contexts,
    )


async def calculate_context_precision(
    config: AppConfig,
    metric: ContextPrecisionWithoutReference,
    sample: SingleTurnSample,
) -> float:
    """Run the ragas metric and return only the numeric score value."""

    # Ask ragas to score the retrieved contexts against the generated answer.
    score = await metric.ascore(
        user_input=sample.user_input,
        response=sample.response,
        retrieved_contexts=sample.retrieved_contexts,
    )
    # Return the numeric score stored inside the ragas result object.
    return score.value


async def run_context_precision(config: AppConfig = CONFIG) -> float:
    """Execute the full RAG fetch plus context precision scoring workflow."""

    # Mirror the selected key into the process environment for libraries that still read it.
    os.environ["OPENAI_API_KEY"] = config.llm_api_key
    # Build the configured metric instance.
    metric = build_metric(config)
    # Call the RAG endpoint and collect the answer plus retrieved contexts.
    rag_response = fetch_rag_response(config)
    # Print the raw RAG payload so the user can inspect what is being scored.
    print(rag_response)
    # Convert the raw payload into the sample format expected by ragas.
    sample = build_sample(config, rag_response)
    # Print how many retrieved contexts are included in the metric input.
    print(f"No of context retrieved: {len(sample.retrieved_contexts)}")

    # Try to compute the score and surface config details if the LLM call fails.
    try:
        score = await calculate_context_precision(config, metric, sample)
    # Catch any failure so the printed diagnostics are still helpful.
    except Exception as exc:
        # Print a short high-level error message for the LLM scoring stage.
        print(
            "LLM scoring failed. Check LLM_API_ENDPOINT, LLM_MODEL, and the API key configured in 1.env."
        )
        # Print the normalized base URL actually used by the client.
        print(f"Configured endpoint: {config.llm_base_url}")
        # Print the configured model name used during scoring.
        print(f"Configured model: {config.llm_model}")
        # Re-raise the original exception so pytest still fails properly.
        raise exc

    # Print the final score for manual script runs.
    print(score)
    # Return the final numeric score to the caller.
    return score


@pytest.mark.asyncio
async def test_context_precision() -> None:
    """Pytest entry point that validates the score stays above the configured threshold."""

    # Run the shared workflow used by both the test and the direct script mode.
    score = await run_context_precision()
    # Assert the score stays above the configured pass threshold.
    assert score > CONFIG.score_threshold


def main() -> int:
    """Run the script directly and return a shell-friendly exit code."""

    # Try to execute the async workflow from a normal Python process.
    try:
        asyncio.run(run_context_precision())
    # Convert unexpected runtime failures into a clean non-zero exit code.
    except Exception:
        # Print a short message after the detailed diagnostics above.
        print("No score produced.")
        # Return a failure status code to the shell.
        return 1
    # Return success when the workflow completes.
    return 0


# Run the script entry point when the file is executed directly.
if __name__ == "__main__":
    # Exit the process with the status code returned by main().
    raise SystemExit(main())
