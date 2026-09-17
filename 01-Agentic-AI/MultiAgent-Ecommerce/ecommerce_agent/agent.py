import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import AgentTool, FunctionTool
from typing import Dict

from google.adk.tools import ToolContext
from catalog_agent.agent import catalog_agent



load_dotenv()  # pull OLLAMA_API_KEY from .env

# IMPORTANT: Ollama Cloud (https://ollama.com) exposes TWO API surfaces:
#   1. Native Ollama API:  https://ollama.com/api/chat   (LiteLLM provider `ollama/`)
#   2. OpenAI-compatible:  https://ollama.com/v1/chat/completions  (LiteLLM provider `openai/`)
#
# The native ollama/ provider forces `format: json` when tools are attached,
# which makes gpt-oss:120b return empty content → JSONDecodeError in LiteLLM.
# The OpenAI-compatible endpoint handles tool calling the standard OpenAI way
# (native function calling), which gpt-oss supports correctly. So we use `openai/`.
_ollama_key = os.environ["OLLAMA_API_KEY"]


def save_user_info(
    tool_context: ToolContext, name: str, email: str, mobile: str
):
    tool_context.state["name"] = name
    tool_context.state["email"] = email
    tool_context.state["mobile"] = mobile


root_agent = LlmAgent(
    name="ecommerce_agent",
    model=LiteLlm(
        model="openai/gpt-oss:120b",
        api_base="https://ollama.com/v1",
        api_key=_ollama_key,
        extra_headers={"Authorization": f"Bearer {_ollama_key}"},
    ),
    description="An ecommerce agent that manages the ecommmerce workflow",
    instruction="""Role: You are an ecommerce agent who can help the user with product catalog, checkout and order tracking.

Workflow:
- Greet the user and give a brief introduction about yourself on how can you help and then start gatherin the user details as mentioned below. DO not directly start gathering user information.
- If you do not know, ask for the user's name, email and mobile number. Ask only one information at a time.
- Once you have ALL THREE pieces of information (name, email, mobile), call the save_user_info() tool to save these information into shared state BEFORE doing anything else. This is mandatory - the sub-agents rely on this state.
- After save_user_info() has been called, confirm the saved info back to the user in one line, then understand the user's intent. Are they looking for new purchase or track an existing order.
- Based on the user's request and route it to ONE of your sub-agents:
  - catalog_agent - For New purchases, questions about products, prices, availability etc.
  - checkout_agent - For checkout of items in cart.
  - tracking_agent - For tracking existing orders.

Rules:
1. NEVER answer the question yourself. Always delegate to exactly one sub-agent.
2. If the user's message clearly matches one category, immediately call that agent.
3. If you are unsure, ask a short clarifying question instead of guessing.
4. After a sub-agent responds, you may send that response back as-is to the user, without adding extra content.
5. NEVER route to checkout_agent before save_user_info() has been called. If the user jumps straight to checkout, first collect name/email/mobile and call save_user_info(), then route.
""",
    tools=[save_user_info],
    sub_agents=[catalog_agent]
)
root_agent = root_agent