import os
import json

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import ToolContext
from order_summary_agent.agent import order_summary_agent

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


def save_shipping_address(tool_context: ToolContext, address: str):
    tool_context.state["shipping_address"] = address


checkout_agent = LlmAgent(
    name="checkout_agent",
    model=LiteLlm(
        model="openai/gpt-oss:120b",
        api_base="https://ollama.com/v1",
        api_key=_ollama_key,
        extra_headers={"Authorization": f"Bearer {_ollama_key}"},
    ),
    description="A Checkout agent that collects user's shipping address",
    instruction="""
You are CHECKOUT AGENT.

Goal:
- Collect the user's shipping address.
- Use the save_shipping_address to save the shipping address into the SESSION STATE.
- Then check with the user if they want to view their order summary and transfer to the order_summary agent.
""",
    tools=[save_shipping_address],
    sub_agents=[order_summary_agent],
)