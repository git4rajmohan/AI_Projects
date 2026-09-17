import os
import json

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import ToolContext


load_dotenv()

# IMPORTANT: Ollama Cloud (https://ollama.com) exposes TWO API surfaces:
#   1. Native Ollama API:  https://ollama.com/api/chat   (LiteLLM provider `ollama/`)
#   2. OpenAI-compatible:  https://ollama.com/v1/chat/completions  (LiteLLM provider `openai/`)
#
# The native ollama/ provider forces `format: json` when tools are attached,
# which makes gpt-oss:120b return empty content -> JSONDecodeError in LiteLLM.
# The OpenAI-compatible endpoint handles tool calling the standard OpenAI way
# (native function calling), which gpt-oss supports correctly. So we use `openai/`.
_ollama_key = os.environ["OLLAMA_API_KEY"]


order_summary_agent = LlmAgent(
    name="order_summary_agent",
    model=LiteLlm(
        model="openai/gpt-oss:120b",
        api_base="https://ollama.com/v1",
        api_key=_ollama_key,
        extra_headers={"Authorization": f"Bearer {_ollama_key}"},
    ),
    description="An order summary agent that gives a summary of the complete order",
    instruction="""
Goal:
- Read the COMPLETE ORDER INFORMATION from SESSION STATE.
- Present a clear, friendly summary of the order to the user.

Use the following information from the state object and generate an order summary. The summary should be user friendly and should look like how amazon or flipkart generates them.

{name} {email} {mobile}
{item} {quantity} {price} {shipping_address}

Rule:
Read ONLY from state; do NOT invent random information that are not in state.
"""
)