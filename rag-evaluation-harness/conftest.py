import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv


ENV_FILE = Path(__file__).with_name("1.env")
OPENAI_COMPLETION_SUFFIXES = ("/chat/completions", "/completions")


load_dotenv(ENV_FILE, override=True)


def ensure_vertexai_compatibility() -> None:
    if "langchain_community.chat_models.vertexai" in sys.modules:
        return

    vertexai_module = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:
        pass

    vertexai_module.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = vertexai_module


ensure_vertexai_compatibility()


from ragas.llms import llm_factory


def get_required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def normalize_openai_base_url(endpoint: str) -> str:
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


def patch_async_client_for_baseten(client: Any) -> Any:
    original_create = client.chat.completions.create

    async def create_with_normalized_content(*args, **kwargs):
        response = await original_create(*args, **kwargs)
        return normalize_response_content(response)

    client.chat.completions.create = create_with_normalized_content
    return client


@pytest.fixture
def llm_wrapper():
    from openai import AsyncOpenAI

    llm_api_key = get_required_setting("OPENAI_API_KEY")
    llm_api_endpoint = get_required_setting("LLM_API_ENDPOINT")
    llm_model = get_required_setting("LLM_MODEL")
    llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0"))

    os.environ["OPENAI_API_KEY"] = llm_api_key

    client = AsyncOpenAI(
        api_key=llm_api_key,
        base_url=normalize_openai_base_url(llm_api_endpoint),
    )
    client = patch_async_client_for_baseten(client)
    return llm_factory(
        llm_model,
        client=client,
        temperature=llm_temperature,
    )
