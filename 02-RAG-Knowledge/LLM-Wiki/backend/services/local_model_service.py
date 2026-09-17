"""
Local CPU model service — downloads and runs GGUF models via llama-cpp-python.
Supports multiple open-access models. All inference runs on CPU.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from typing import AsyncGenerator, List, Optional


def _get_models_dir() -> Path:
    """Return the models directory — next to the exe when frozen, or project root when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "models"
    return Path(__file__).parent.parent.parent / "models"


# Store models inside the project folder
MODELS_DIR = _get_models_dir()

# ── Model catalog ────────────────────────────────────────────────────────────
# Each entry: id (used in config), repo (HF repo), filename (GGUF file),
#             size (approx), prompt_style (chat template format)
AVAILABLE_MODELS = [
    {
        "id": "gemma-2-2b-it",
        "label": "Gemma 2 2B Instruct",
        "repo": "bartowski/gemma-2-2b-it-GGUF",
        "filename": "gemma-2-2b-it-Q4_K_M.gguf",
        "size": "1.7 GB",
        "prompt_style": "gemma",
    },
    {
        "id": "llama-3.2-3b-instruct",
        "label": "Llama 3.2 3B Instruct",
        "repo": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size": "2.0 GB",
        "prompt_style": "llama3",
    },
    {
        "id": "qwen2.5-3b-instruct",
        "label": "Qwen 2.5 3B Instruct",
        "repo": "bartowski/Qwen2.5-3B-Instruct-GGUF",
        "filename": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "size": "2.0 GB",
        "prompt_style": "chatml",
    },
    {
        "id": "phi-3.5-mini-instruct",
        "label": "Phi 3.5 Mini Instruct",
        "repo": "bartowski/Phi-3.5-mini-instruct-GGUF",
        "filename": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size": "2.2 GB",
        "prompt_style": "chatml",
    },
    {
        "id": "gemma-4-E2B-it",
        "label": "Gemma 4 E2B Instruct",
        "repo": "bartowski/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "size": "1.9 GB",
        "prompt_style": "gemma",
    },
]

# Backward compat — default model
DEFAULT_MODEL_ID = "gemma-2-2b-it"


def get_model_info(model_id: str) -> dict:
    """Return the catalog entry for a model id."""
    for m in AVAILABLE_MODELS:
        if m["id"] == model_id:
            return m
    # Fallback: try to find by filename match (for legacy config)
    return AVAILABLE_MODELS[0]


def get_model_path(model_id: str = None) -> Path:
    """Return the local path for a downloaded GGUF model."""
    if model_id is None:
        model_id = DEFAULT_MODEL_ID
    info = get_model_info(model_id)
    return MODELS_DIR / info["filename"]


def is_model_downloaded(model_id: str = None) -> bool:
    """Check if the model file exists on disk."""
    if model_id is None:
        model_id = DEFAULT_MODEL_ID
    mp = get_model_path(model_id)
    return mp.exists() and mp.stat().st_size > 1_000_000  # at least 1 MB


def get_downloaded_models() -> list[str]:
    """Return list of model IDs that are downloaded and ready."""
    return [m["id"] for m in AVAILABLE_MODELS if is_model_downloaded(m["id"])]


def download_model(model_id: str) -> str:
    """Download a GGUF model from Hugging Face Hub. Returns the local path.

    This is a blocking call — run it in a thread.
    """
    from huggingface_hub import hf_hub_download

    info = get_model_info(model_id)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    local_path = hf_hub_download(
        repo_id=info["repo"],
        filename=info["filename"],
        local_dir=str(MODELS_DIR),
    )
    return local_path


# ── Singleton llama-cpp model instance ──────────────────────────────────────
# Keyed by model_id so switching models reloads

_llm_instances: dict[str, object] = {}
_llm_lock = threading.Lock()


def _get_llm(model_id: str = None):
    """Lazily load the llama-cpp model (cached per model_id, thread-safe)."""
    if model_id is None:
        model_id = DEFAULT_MODEL_ID
    if model_id in _llm_instances:
        return _llm_instances[model_id]
    with _llm_lock:
        if model_id in _llm_instances:
            return _llm_instances[model_id]
        from llama_cpp import Llama

        model_path = str(get_model_path(model_id))
        _llm_instances[model_id] = Llama(
            model_path=model_path,
            n_ctx=16384,         # context window — large enough for schema + source + output
            n_threads=max(1, (os.cpu_count() or 4) - 1),
            n_gpu_layers=0,       # CPU only
            verbose=False,
        )
        return _llm_instances[model_id]


def _build_prompt(messages: List[dict], prompt_style: str) -> str:
    """Build a chat prompt from message list based on the model's prompt style."""
    if prompt_style == "gemma":
        # Gemma 2 instruct: <start_of_turn>user\n...<end_of_turn>
        parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                parts.append(f"<start_of_turn>user\n{content}<end_of_turn>")
            elif role == "user":
                parts.append(f"<start_of_turn>user\n{content}<end_of_turn>")
            elif role == "assistant":
                parts.append(f"<start_of_turn>model\n{content}<end_of_turn>")
        parts.append("<start_of_turn>model\n")
        return "\n".join(parts)

    elif prompt_style == "llama3":
        # Llama 3.2: <|im_start|>user\n...<|im_end|>
        parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                parts.append(f"<|im_start|>system\n{content}<|im_end|>")
            elif role == "user":
                parts.append(f"<|im_start|>user\n{content}<|im_end|>")
            elif role == "assistant":
                parts.append(f"<|im_start|>assistant\n{content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    else:
        # ChatML (Qwen, Phi, etc.): <|im_start|>role\n...<|im_end|>
        parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)


def _get_stop_tokens(prompt_style: str) -> list[str]:
    """Return stop tokens for the given prompt style.

    NOTE: Do NOT include <|channel> tokens as stop tokens for Gemma 4 E2B.
    That model uses <|channel>thought ... <|channel>response ... pattern,
    and stopping on <|channel> kills generation before the actual response
    is produced. The _strip_thinking() function in ingest_service.py handles
    removing thinking blocks from the final output.
    """
    if prompt_style == "gemma":
        return ["<end_of_turn>", "<start_of_turn>"]
    else:
        return ["<|im_end|>", "<|im_start|>"]


def _truncate_messages(messages: List[dict], max_chars: int = 12000) -> List[dict]:
    """Truncate message list to fit within a character budget.
    Keeps the system message (if any) and the most recent messages."""
    if not messages:
        return messages
    total = sum(len(m["content"]) for m in messages)
    if total <= max_chars:
        return messages
    # Always keep system message
    system_msgs = [m for m in messages if m["role"] == "system"]
    non_system = [m for m in messages if m["role"] != "system"]
    # Keep the most recent non-system messages that fit
    result = list(system_msgs)
    remaining_budget = max_chars - sum(len(m["content"]) for m in result)
    kept = []
    for msg in reversed(non_system):
        if remaining_budget - len(msg["content"]) < 0:
            break
        kept.insert(0, msg)
        remaining_budget -= len(msg["content"])
    return result + kept


async def chat_completion(
    messages: List[dict],
    temperature: float = 0.3,
    max_tokens: int = 2048,
    model_id: str = None,
) -> str:
    """Single-shot completion, returns full response string."""
    if model_id is None:
        model_id = DEFAULT_MODEL_ID
    info = get_model_info(model_id)
    loop = asyncio.get_event_loop()

    def _run():
        llm = _get_llm(model_id)
        truncated = _truncate_messages(messages)
        prompt = _build_prompt(truncated, info["prompt_style"])
        stop_tokens = _get_stop_tokens(info["prompt_style"])

        # Gemma 4 E2B sometimes generates EOS (<end_of_turn>) as its very
        # first token, producing 0 output. Retry with a different seed
        # and increasing temperature until we get actual content.
        import random as _random
        for attempt in range(3):
            seed = _random.randint(0, 2**31 - 1) if attempt > 0 else None
            kwargs = dict(
                prompt=prompt,
                max_tokens=min(max_tokens, 6144),
                temperature=max(temperature, 0.1 * attempt),
                stop=stop_tokens,
                echo=False,
            )
            if seed is not None:
                kwargs["seed"] = seed
            result = llm(**kwargs)
            text = result["choices"][0]["text"].strip()
            if text:
                return text
        return ""  # All attempts failed

    return await loop.run_in_executor(None, _run)


async def stream_completion(
    messages: List[dict],
    temperature: float = 0.3,
    max_tokens: int = 2048,
    model_id: str = None,
) -> AsyncGenerator[str, None]:
    """Streaming completion — yields text chunks."""
    if model_id is None:
        model_id = DEFAULT_MODEL_ID
    info = get_model_info(model_id)
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def _run():
        try:
            llm = _get_llm(model_id)
            truncated = _truncate_messages(messages)
            prompt = _build_prompt(truncated, info["prompt_style"])
            stop_tokens = _get_stop_tokens(info["prompt_style"])

            # Gemma 4 E2B sometimes generates EOS as its first token.
            # Retry with different seeds until we get actual content.
            import random as _random
            for attempt in range(3):
                seed = _random.randint(0, 2**31 - 1) if attempt > 0 else None
                kwargs = dict(
                    prompt=prompt,
                    max_tokens=min(max_tokens, 6144),
                    temperature=max(temperature, 0.1 * attempt),
                    stop=stop_tokens,
                    echo=False,
                    stream=True,
                )
                if seed is not None:
                    kwargs["seed"] = seed

                got_text = False
                for chunk in llm(**kwargs):
                    text = chunk["choices"][0]["text"]
                    if text:
                        got_text = True
                        asyncio.run_coroutine_threadsafe(queue.put(text), loop)
                if got_text:
                    break  # Success — don't retry
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                queue.put({"__error__": str(e)}), loop
            )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop)

    loop.run_in_executor(None, _run)

    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, dict) and "__error__" in item:
            raise RuntimeError(item["__error__"])
        yield item


async def test_connection(model_id: str = None) -> str:
    """Send a minimal test prompt. Returns 'ok' or raises."""
    if model_id is None:
        model_id = DEFAULT_MODEL_ID
    if not is_model_downloaded(model_id):
        raise RuntimeError("Model not downloaded yet. Click 'Download Model' first.")
    result = await chat_completion(
        [{"role": "user", "content": "Reply with exactly: ok"}],
        temperature=0.0,
        max_tokens=10,
        model_id=model_id,
    )
    return result.strip()