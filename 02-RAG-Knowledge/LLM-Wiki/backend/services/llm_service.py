"""
LLM service — routes to the correct SDK based on provider config.
Supports: OpenAI, Azure OpenAI, Anthropic, Ollama, LM Studio, Together AI, Baseten,
          Local CPU Model (multiple GGUF models via llama-cpp-python).
No third-party abstraction libraries — only openai + anthropic SDKs.
"""
from __future__ import annotations

from typing import AsyncGenerator, List

from backend.config import LLMConfig
from backend.services import local_model_service

# Provider base URLs for OpenAI-compatible APIs
PROVIDER_BASE_URLS = {
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "together": "https://api.together.xyz/v1",
    # baseten base_url is model-specific, must be set manually in config
}


def _get_openai_client(cfg: LLMConfig):
    import openai

    if cfg.provider == "azure":
        return openai.AsyncAzureOpenAI(
            api_key=cfg.api_key,
            azure_endpoint=cfg.azure_endpoint,
            api_version=cfg.azure_api_version,
        )

    base_url = cfg.base_url or PROVIDER_BASE_URLS.get(cfg.provider)
    # Strip trailing /chat/completions — the OpenAI SDK appends it automatically.
    # Users often paste the full endpoint URL from provider docs.
    if base_url and base_url.rstrip("/").endswith("/chat/completions"):
        base_url = base_url.rstrip("/").rsplit("/chat/completions", 1)[0]
    # Ollama and LM Studio don't require a real API key
    keyless_providers = {"ollama", "lmstudio"}
    api_key = cfg.api_key or ("no-key" if cfg.provider in keyless_providers else None)
    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None,
    )


async def chat_completion(cfg: LLMConfig, messages: List[dict]) -> str:
    """Single-shot completion, returns full response string."""
    if cfg.provider == "local-cpu":
        return await local_model_service.chat_completion(
            messages, temperature=cfg.temperature, max_tokens=cfg.max_tokens,
            model_id=cfg.model,
        )

    if cfg.provider == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=cfg.api_key)
        # Separate system message if present
        system = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_messages.append(m)
        response = await client.messages.create(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=system or anthropic.NOT_GIVEN,
            messages=user_messages,
        )
        return response.content[0].text

    client = _get_openai_client(cfg)
    model = cfg.azure_deployment if cfg.provider == "azure" else cfg.model
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )
    return response.choices[0].message.content


async def stream_completion(
    cfg: LLMConfig, messages: List[dict]
) -> AsyncGenerator[str, None]:
    """Streaming completion — yields text chunks."""
    if cfg.provider == "local-cpu":
        async for chunk in local_model_service.stream_completion(
            messages, temperature=cfg.temperature, max_tokens=cfg.max_tokens,
            model_id=cfg.model,
        ):
            yield chunk
        return

    if cfg.provider == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=cfg.api_key)
        system = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_messages.append(m)
        async with client.messages.stream(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=system or anthropic.NOT_GIVEN,
            messages=user_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
        return

    client = _get_openai_client(cfg)
    model = cfg.azure_deployment if cfg.provider == "azure" else cfg.model
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def test_connection(cfg: LLMConfig) -> str:
    """Send a minimal test prompt. Returns 'ok' or raises."""
    if cfg.provider == "local-cpu":
        if not local_model_service.is_model_downloaded(cfg.model):
            raise RuntimeError(
                "Model not downloaded yet. Click 'Download Model' first."
            )
        result = await local_model_service.test_connection(cfg.model)
        return result.strip()

    result = await chat_completion(cfg, [{"role": "user", "content": "Reply with: ok"}])
    return result.strip()
