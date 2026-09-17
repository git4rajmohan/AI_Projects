import os
import re
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv
from openai import OpenAI

from config.settings import CHAT_BASE_URL, CHAT_MODEL
from generation.prompt_builder import PromptMessages

load_dotenv()


@dataclass
class Answer:
    text: str
    citations: List[str]   # extracted citation strings from the answer text
    query: str
    chunks_used: int


def generate(
    prompt: PromptMessages,
    query: str,
    chunks_used: int,
    max_tokens: int = 2048,
    temperature: float | None = None,
) -> Answer:
    """
    Call the chat LLM (Ollama Cloud, OpenAI-compatible endpoint) with the prompt messages.
    Parse citation strings from the response (lines matching '[Source: ..., Section: ...]').
    Return an Answer dataclass.
    Model: from config.settings.CHAT_MODEL (OLLAMA_CHAT_MODEL in .env)
    Max tokens: 2048 (gpt-oss is a reasoning model; thinking tokens count toward the budget)
    Temperature: None = provider default (matches original behavior); 0 = deterministic.
    Reads OLLAMA_API_KEY from environment variables using python-dotenv.
    """
    client = OpenAI(
        base_url=CHAT_BASE_URL,
        api_key=os.getenv("OLLAMA_API_KEY"),
    )

    create_kwargs: dict = {
        "model": CHAT_MODEL,
        "max_tokens": max_tokens,  # gpt-oss is a reasoning model; thinking tokens count toward the budget
        "messages": [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
    }
    if temperature is not None:
        create_kwargs["temperature"] = temperature

    response = client.chat.completions.create(**create_kwargs)

    text = response.choices[0].message.content or ""
    citations = re.findall(r'\[Source: .+?, Section: .+?\]', text)

    return Answer(
        text=text,
        citations=citations,
        query=query,
        chunks_used=chunks_used,
    )
