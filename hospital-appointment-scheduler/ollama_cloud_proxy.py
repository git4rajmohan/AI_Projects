"""
Ollama Cloud Proxy
==================
A lightweight FastAPI server that translates OpenAI-compatible API calls
into Ollama Cloud native format, allowing langchain-openai's ChatOpenAI
to use Ollama Cloud models seamlessly.

Start this BEFORE running the app or tests:
    .venv\\Scripts\\python.exe ollama_cloud_proxy.py

Endpoints:
    POST /v1/chat/completions  →  Ollama /api/chat
    GET  /v1/models            →  lists available Ollama models
    GET  /health               →  proxy health check
"""

import json
import os
import logging
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

OLLAMA_CLOUD_URL = os.getenv("OLLAMA_CLOUD_URL", "https://ollama.com/api/chat")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "11435"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ollama-proxy")

app = FastAPI(title="Ollama Cloud Proxy", version="1.0.0")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _strip_prefix(model: str) -> str:
    """Strip 'openai/' prefix that langchain adds."""
    if model.startswith("openai/"):
        return model[len("openai/"):]
    return model


def _flatten_content(content: Any) -> str:
    """Flatten OpenAI content (string or array of parts) to plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content)


def _translate_messages_openai_to_ollama(messages: list[dict]) -> list[dict]:
    """Translate OpenAI message format → Ollama message format."""
    ollama_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = _flatten_content(msg.get("content", ""))

        # Handle tool_calls in assistant messages
        if msg.get("tool_calls"):
            # Ollama expects tool_calls as a list of {function: {name, arguments}}
            ollama_tool_calls = []
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                ollama_tool_calls.append({
                    "function": {
                        "name": func.get("name", ""),
                        "arguments": args,
                    }
                })
            ollama_messages.append({
                "role": role,
                "content": content,
                "tool_calls": ollama_tool_calls,
            })
        # Handle tool result messages
        elif role == "tool":
            ollama_messages.append({
                "role": "tool",
                "content": content,
            })
        else:
            ollama_messages.append({"role": role, "content": content})

    return ollama_messages


def _translate_tools_openai_to_ollama(tools: list[dict] | None) -> list[dict] | None:
    """Translate OpenAI tool definitions → Ollama tool format."""
    if not tools:
        return None

    ollama_tools = []
    for tool in tools:
        func = tool.get("function", tool)
        params = func.get("parameters", {})
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {"type": "object", "properties": {}}

        ollama_tools.append({
            "type": "function",
            "function": {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": params,
            },
        })
    return ollama_tools


def _translate_response_ollama_to_openai(
    ollama_resp: dict, model: str
) -> dict:
    """Translate Ollama chat response → OpenAI chat completion format."""
    message = ollama_resp.get("message", {})
    content = message.get("content", "")
    tool_calls = message.get("tool_calls", [])

    openai_tool_calls = None
    if tool_calls:
        openai_tool_calls = []
        for i, tc in enumerate(tool_calls):
            func = tc.get("function", {})
            args = func.get("arguments", {})
            if isinstance(args, dict):
                args = json.dumps(args)
            openai_tool_calls.append({
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": func.get("name", ""),
                    "arguments": args,
                },
            })

    openai_message = {
        "role": message.get("role", "assistant"),
        "content": content,
    }
    if openai_tool_calls:
        openai_message["tool_calls"] = openai_tool_calls

    return {
        "id": f"chatcmpl-{ollama_resp.get('created_at', '')}",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": openai_message,
                "finish_reason": "tool_calls" if openai_tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": ollama_resp.get("prompt_eval_count", 0),
            "completion_tokens": ollama_resp.get("eval_count", 0),
            "total_tokens": ollama_resp.get("prompt_eval_count", 0)
            + ollama_resp.get("eval_count", 0),
        },
    }


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "proxy": "ollama-cloud", "upstream": OLLAMA_CLOUD_URL}


@app.get("/v1/models")
async def list_models():
    """Return a minimal models list (OpenAI format)."""
    return {
        "object": "list",
        "data": [
            {"id": "gpt-oss:120b", "object": "model", "owned_by": "ollama"},
            {"id": "gpt-oss:20b", "object": "model", "owned_by": "ollama"},
            {"id": "glm-5.2", "object": "model", "owned_by": "ollama"},
            {"id": "kimi-k2.6", "object": "model", "owned_by": "ollama"},
            {"id": "deepseek-v4-flash", "object": "model", "owned_by": "ollama"},
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Translate OpenAI chat/completions → Ollama /api/chat."""
    body = await request.json()

    model = _strip_prefix(body.get("model", "gpt-oss:120b"))
    messages = _translate_messages_openai_to_ollama(body.get("messages", []))
    tools = _translate_tools_openai_to_ollama(body.get("tools"))
    stream = body.get("stream", False)

    # Build Ollama payload
    ollama_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }

    # Pass through supported params
    for param in ("temperature", "top_p", "max_tokens", "seed"):
        val = body.get(param)
        if val is not None:
            if param == "max_tokens":
                ollama_payload["options"] = ollama_payload.get("options", {})
                ollama_payload["options"]["num_predict"] = val
            else:
                ollama_payload["options"] = ollama_payload.get("options", {})
                ollama_payload["options"][param] = val

    if tools:
        ollama_payload["tools"] = tools

    # Format (for structured output)
    fmt = body.get("response_format")
    if fmt and isinstance(fmt, dict) and fmt.get("type") == "json_object":
        ollama_payload["format"] = "json"

    logger.info(f"→ Ollama: model={model}, msgs={len(messages)}, tools={len(tools or [])}, stream={stream}")

    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    if stream:
        async def stream_generator():
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST", OLLAMA_CLOUD_URL, json=ollama_payload, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        logger.error(f"Ollama error {resp.status_code}: {error_body}")
                        yield f"data: {json.dumps({'error': error_body.decode()})}\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                            openai_chunk = {
                                "id": "chatcmpl-stream",
                                "object": "chat.completion.chunk",
                                "created": 0,
                                "model": model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "role": "assistant",
                                            "content": chunk.get("message", {}).get("content", ""),
                                        },
                                        "finish_reason": "stop" if chunk.get("done") else None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(openai_chunk)}\n\n"
                        except json.JSONDecodeError:
                            continue
                    yield "data: [DONE]\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # Non-streaming
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(OLLAMA_CLOUD_URL, json=ollama_payload, headers=headers)

    if resp.status_code != 200:
        logger.error(f"Ollama error {resp.status_code}: {resp.text}")
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": resp.text, "type": "upstream_error"}},
        )

    ollama_resp = resp.json()
    openai_resp = _translate_response_ollama_to_openai(ollama_resp, model)

    logger.info(f"← OpenAI response: finish={openai_resp['choices'][0]['finish_reason']}")
    return JSONResponse(content=openai_resp)


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    """Translate OpenAI embeddings → Ollama /api/embed (note: Ollama cloud may not support this)."""
    body = await request.json()
    model = _strip_prefix(body.get("model", "nomic-embed-text"))
    input_text = body.get("input", "")

    if isinstance(input_text, list):
        input_text = input_text[0] if input_text else ""

    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://ollama.com/api/embed",
            json={"model": model, "input": input_text},
            headers=headers,
        )

    if resp.status_code != 200:
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": resp.text, "type": "upstream_error"}},
        )

    ollama_resp = resp.json()
    embeddings_list = ollama_resp.get("embeddings", [])

    return JSONResponse(
        content={
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": emb}
                for i, emb in enumerate(embeddings_list)
            ],
            "model": model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }
    )


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not OLLAMA_API_KEY or OLLAMA_API_KEY == "your_real_ollama_cloud_key_here":
        logger.warning("OLLAMA_API_KEY not set — proxy will fail upstream auth!")

    logger.info(f"Starting Ollama Cloud Proxy on {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"Upstream: {OLLAMA_CLOUD_URL}")
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT, log_level="info")