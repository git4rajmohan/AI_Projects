"""Health-check script for the Enterprise Knowledge Assistant.

Verifies, with REAL responses only (no fabricated "Connected"):
  1. Local Ollama daemon reachable at OLLAMA_BASE_URL (/api/tags).
  2. nomic-embed-text (or configured OLLAMA_EMBED_MODEL) present locally.
  3. Ollama Cloud reachable (OLLAMA_CLOUD_BASE_URL) with API key and the
     configured OLLAMA_LLM_MODEL actually responds to a tiny chat request.
  4. Qdrant reachable at QDRANT_URL (GET / reports real version).

Exit code 0 when all checks pass, 1 otherwise.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import requests
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this script).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import os  # noqa: E402  (after load_dotenv so values are populated)

GREEN = "\u2705"
RED = "\u274c"
YELLOW = "\u26a0\ufe0f"


def _check_local_ollama(base_url: str) -> tuple[bool, str]:
    """Check (1): local Ollama daemon responds on /api/tags."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        return True, f"daemon up at {base_url}, {len(names)} models listed"
    except Exception as exc:  # noqa: BLE001 — report any failure verbatim
        return False, f"daemon unreachable at {base_url}: {exc}"


def _check_embed_model(base_url: str, embed_model: str) -> tuple[bool, str]:
    """Check (2): the configured embedding model exists on the local daemon."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        base_tag = embed_model.split(":")[0]
        found = any(n == embed_model or n.split(":")[0] == base_tag for n in names)
        if found:
            return True, f"'{embed_model}' available on local daemon"
        return False, f"'{embed_model}' NOT found; run: ollama pull {embed_model}"
    except Exception as exc:  # noqa: BLE001
        return False, f"could not list local models: {exc}"


def _check_ollama_cloud(cloud_url: str, api_key: str, llm_model: str) -> tuple[bool, str]:
    """Check (3): Ollama Cloud chat endpoint with real API key + model tag.

    Uses the native Ollama format (NOT OpenAI format) per project decision.
    """
    if not api_key or api_key.startswith("<"):
        return False, "OLLAMA_API_KEY missing or placeholder in .env"
    try:
        resp = requests.post(
            f"{cloud_url.rstrip('/')}/chat",
            json={
                "model": llm_model,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=90,
        )
        resp.raise_for_status()
        content: str = resp.json().get("message", {}).get("content", "")
        ok = bool(content.strip())
        return ok, (
            f"'{llm_model}' responded ({len(content)} chars) via {cloud_url}"
            if ok
            else f"'{llm_model}' returned empty content"
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"cloud chat failed for '{llm_model}' at {cloud_url}: {exc}"


def _check_qdrant(qdrant_url: str, api_key: str | None = None) -> tuple[bool, str]:
    """Check (4): Qdrant responds on GET / with a real version string."""
    headers = {"api-key": api_key} if api_key else None
    try:
        resp = requests.get(qdrant_url.rstrip("/"), headers=headers, timeout=5)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return True, f"up at {qdrant_url}, version {data.get('version', 'unknown')}"
    except Exception as exc:  # noqa: BLE001
        return False, f"unreachable at {qdrant_url}: {exc}"


def run_all_checks(parallel: bool = False) -> tuple[bool, list[tuple[str, bool, str]]]:
    """Run all four service checks; returns (all_passed, [(name, ok, detail)]).

    ``parallel=True`` (used by the UI) runs the probes concurrently — they are
    independent HTTP calls, so wall-clock drops from the sequential sum
    (~15-25 s, dominated by the Ollama Cloud chat ping) to the slowest single
    probe. CLI keeps ``parallel=False`` and preserves its output order.
    """
    provider = os.getenv("OLLAMA_PROVIDER", "local")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    cloud_url = os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api")
    api_key = os.getenv("OLLAMA_API_KEY", "")
    llm_model = os.getenv("OLLAMA_LLM_MODEL", "gpt-oss:120b")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_key = os.getenv("QDRANT_API_KEY") or None

    probes: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
        ("Local Ollama daemon", lambda: _check_local_ollama(base_url)),
        (f"Embedding model '{embed_model}'", lambda: _check_embed_model(base_url, embed_model)),
    ]
    if provider == "cloud":
        probes.append(
            (f"Ollama Cloud '{llm_model}'", lambda: _check_ollama_cloud(cloud_url, api_key, llm_model))
        )
    else:
        probes.append((f"Local LLM '{llm_model}'", lambda: _check_local_llm(base_url, llm_model)))
    probes.append(("Qdrant", lambda: _check_qdrant(qdrant_url, qdrant_key)))

    if parallel:
        with ThreadPoolExecutor(max_workers=len(probes)) as pool:
            futures = [(name, pool.submit(fn)) for name, fn in probes]
            results = [(name, *fut.result()) for name, fut in futures]
    else:
        results = [(name, *fn()) for name, fn in probes]

    return all(ok for _, ok, _ in results), results


def _check_local_llm(base_url: str, llm_model: str) -> tuple[bool, str]:
    """Check local daemon's LLM availability via /api/tags."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        base_tag = llm_model.split(":")[0]
        found = any(n == llm_model or n.split(":")[0] == base_tag for n in names)
        if found:
            return True, f"'{llm_model}' available locally"
        return False, f"'{llm_model}' NOT found locally; run: ollama pull {llm_model}"
    except Exception as exc:  # noqa: BLE001
        return False, f"could not list local models: {exc}"


def main() -> int:
    print(f"Loaded .env from: {PROJECT_ROOT / '.env'}")
    print(f"OLLAMA_PROVIDER = {os.getenv('OLLAMA_PROVIDER', '(unset)')}\n")
    all_passed, results = run_all_checks()
    for name, ok, detail in results:
        icon = GREEN if ok else RED
        print(f"  {icon} {name}: {detail}")
    print()
    if all_passed:
        print(f"{GREEN} ALL CHECKS PASSED")
        return 0
    print(f"{YELLOW} SOME CHECKS FAILED — fix the failing services above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())