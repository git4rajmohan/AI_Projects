"""Smoke test: .env loads and Ollama Cloud answers one prompt. Run: python smoke_test.py"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()


def ask(prompt: str) -> str:
    """Send one chat message to Ollama Cloud and return the reply text."""
    host = os.environ["OLLAMA_HOST"]
    resp = httpx.post(
        f"{host}/api/chat",
        headers={"Authorization": f"Bearer {os.environ['OLLAMA_API_KEY']}"},
        json={
            "model": os.environ["OLLAMA_MODEL"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


if __name__ == "__main__":
    reply = ask("Reply with exactly one word: pong")
    assert reply.strip(), "empty reply from Ollama Cloud"
    print(f"Ollama Cloud OK - model={os.environ['OLLAMA_MODEL']} reply={reply.strip()!r}")
