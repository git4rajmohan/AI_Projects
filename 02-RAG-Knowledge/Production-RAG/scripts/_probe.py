"""Quick judge latency probe (heredoc-safe)."""
import os
import time

from dotenv import load_dotenv

load_dotenv()
from openai import OpenAI  # noqa: E402

key = os.getenv("OLLAMA_API_KEY")
c = OpenAI(base_url="https://ollama.com/v1", api_key=key, timeout=240)
SYS = 'Extract atomic factual claims as JSON {"claims": [...]} only.'
USR = "RAG stands for Retrieval-Augmented Generation. It retrieves chunks and grounds the LLM."
for model in ["gpt-oss:20b", "glm-5.2"]:
    t0 = time.time()
    try:
        c.chat.completions.create(
            model=model, temperature=0, max_tokens=2000,
            messages=[{"role": "system", "content": SYS},
                      {"role": "user", "content": USR}])
        print(f"{model} NOW: {time.time() - t0:.1f}s OK")
    except Exception as e:
        print(f"{model} NOW: FAIL after {time.time() - t0:.1f}s {type(e).__name__}")