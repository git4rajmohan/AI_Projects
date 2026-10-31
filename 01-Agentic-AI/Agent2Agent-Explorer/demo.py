"""End-to-end demo check: start worker, delegate one task, assert an answer.

Run: .venv\\Scripts\\python.exe demo.py
"""
import asyncio
import subprocess
import sys
import time

import httpx

from coordinator import WORKER_URL, delegate


def main() -> None:
    worker = subprocess.Popen([sys.executable, "worker.py"])
    try:
        for _ in range(50):
            try:
                httpx.get(f"{WORKER_URL}/.well-known/agent-card.json", timeout=1).raise_for_status()
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("worker did not start")
        answer = asyncio.run(delegate("Reply with exactly one word: pong"))
        assert answer.strip(), "no answer from worker agent"
        print(f"demo OK - worker answered: {answer.strip()!r}")
    finally:
        worker.terminate()


if __name__ == "__main__":
    main()
