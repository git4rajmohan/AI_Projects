"""Mindmap generator: sends text to an LLM (Ollama) and gets back a Markdown hierarchy."""

import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# Load .env if present
load_dotenv()

SYSTEM_PROMPT = """\
You are an expert at analyzing text and creating structured mindmaps.

Convert the following text into a hierarchical mindmap using Markdown headings.

Rules:
- Use a single # for the central topic (the title or main theme of the text)
- Use ## for major branches (3 to 7 main concepts)
- Use ### and deeper levels (####, #####) for sub-points, up to 4 levels deep
- Keep each node label concise — maximum 8 words per node
- Capture the logical structure and key ideas, not every detail
- Use the language of the source text (if the text is in Japanese, output Japanese; if English, output English)
- **Bold key terms**: Use **bold** for the most important word or phrase in each node label. \
  For example: "### **GDPR** Compliance" or "### **Gender bias** in hiring"
- **Descriptions**: After each node label, add a brief description (1 sentence, max 15 words) \
  as an HTML comment in this format: <!-- description text --> \
  This provides extra context when hovering over the node. \
  Example: "## **Data Privacy** <!-- Protecting sensitive personal information from unauthorized access -->"
- Output ONLY the Markdown headings — no explanation, no code fences, no preamble

Example output format:
# **Central Topic** <!-- Main theme of the content -->
## **Branch One** <!-- Key concept area -->
### **Sub-point A** <!-- Detail about sub-point A -->
### **Sub-point B** <!-- Detail about sub-point B -->
## **Branch Two** <!-- Another key concept -->
### **Sub-point C** <!-- Detail about sub-point C -->
#### Detail <!-- Further detail -->
## **Branch Three** <!-- Third key concept -->
"""


def _get_client(base_url: Optional[str] = None) -> OpenAI:
    """Create an OpenAI-compatible client pointed at Ollama."""
    url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAI(base_url=url, api_key="ollama")


def generate_mindmap(
    text: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Send text to the LLM and return a Markdown string representing the mindmap.

    Args:
        text: The input text to convert into a mindmap.
        model: Ollama model name (e.g. "gpt-oss:120b"). Falls back to OLLAMA_MODEL env var.
        base_url: Ollama API base URL. Falls back to OLLAMA_BASE_URL env var.

    Returns:
        A Markdown string with hierarchical headings (#, ##, ###, ...).

    Raises:
        Exception: If the LLM call fails (Ollama not running, model not found, etc.).
    """
    model_name = model or os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
    client = _get_client(base_url)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
    )

    markdown = response.choices[0].message.content.strip()

    # Strip code fences if the model wrapped output in ```markdown ... ```
    if markdown.startswith("```"):
        lines = markdown.split("\n")
        # Remove first line (```markdown or ```) and last line (```)
        lines = [l for l in lines[1:] if not l.strip() == "```"]
        markdown = "\n".join(lines).strip()

    return markdown