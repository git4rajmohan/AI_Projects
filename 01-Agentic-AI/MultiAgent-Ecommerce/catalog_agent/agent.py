
import json
import os
import urllib.request

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from typing import Dict
from google.adk.tools import ToolContext

from checkout_agent.agent import checkout_agent
load_dotenv()  # pull OLLAMA_API_KEY and SERPER_API_KEY from .env

# IMPORTANT: Ollama Cloud (https://ollama.com) exposes TWO API surfaces:
#   1. Native Ollama API:  https://ollama.com/api/chat   (LiteLLM provider `ollama/`)
#   2. OpenAI-compatible:  https://ollama.com/v1/chat/completions  (LiteLLM provider `openai/`)
#
# The native ollama/ provider forces `format: json` when tools are attached,
# which makes gpt-oss:120b return empty content → JSONDecodeError in LiteLLM.
# The OpenAI-compatible endpoint handles tool calling the standard OpenAI way
# (native function calling), which gpt-oss supports correctly. So we use `openai/`.
_ollama_key = os.environ["OLLAMA_API_KEY"]
_serper_key = os.environ["SERPER_API_KEY"]

def save_cart(
    tool_context: ToolContext, category: str, product: str, quantity: int, price: str
):
    """Save the user's selected items into the shared session state.

    The catalog agent calls this after the user picks a product and quantity.
    The order_summary_agent later reads `item`, `quantity`, `price` from state.
    We store both a nested `cart` dict AND top-level keys so ADK template
    variables like {item} {quantity} {price} in the order_summary instruction
    resolve correctly.
    """
    cart = {
        "category": category,
        "product": product,
        "quantity": quantity,
        "price": price,
    }
    tool_context.state["cart"] = cart
    # Top-level keys consumed by order_summary_agent's instruction template.
    tool_context.state["item"] = product
    tool_context.state["quantity"] = quantity
    tool_context.state["price"] = price
    return {"status": "saved", "cart": cart}


catalog_agent = LlmAgent(
    name="catalog_agent",
    model=LiteLlm(
        model="openai/gpt-oss:120b",
        api_base="https://ollama.com/v1",
        api_key=_ollama_key,
        extra_headers={"Authorization": f"Bearer {_ollama_key}"},
    ),
    description="A catalog agent that can show products and categories and add items to the cart",
    instruction="""Your scope:
- Answer questions about products, categories, prices, brands, and basic comparisons.
- You can invent a SIMPLE fake catalog for demo:
- Smartphones: Pixel 9 (₹70,000), iPhone 16 (₹90,000), Galaxy S25 (₹75,000)
- Laptops: MacBook Air M3 (₹1,10,000), Dell Inspiron (₹65,000)
- Headphones: Sony WH-1000XM6 (₹30,000), Boat Rockerz (₹2,000)

Workflow:
- Inform the user that you have 3 category of products as mentioned above and ask which category they would like to browse
- Then give the details of the products from that category
- And ask if they want to add any of these items to their shopping cart
- If yes, get the quantity they want to add, then call the save_cart() tool with category, product, quantity and price. The `price` must be the exact price string you already showed the user for that product (e.g. "Rs.70,000"). The tool stores the cart in shared state so the order_summary_agent can read it later.
- Once save_cart() has been called and the item is stored, check if the user wants to checkout. If yes, tell the user you are handing them off to the checkout agent and STOP. The root ecommerce_agent will route the user to checkout_agent which reads the cart and user info (name/email/mobile) already in state.
- Do NOT ask for or save name/email/mobile yourself - that is the root ecommerce_agent's job and it has already done it before routing to you.

Guidelines:
1. Stay ONLY in catalog domain. Do NOT place orders or track orders.
2. Keep answers short and friendly (2 to 3 sentences).
3. If the user asks to "buy", "place order", or "track delivery", say:
"This looks like an order or tracking question. Please ask the assistant again, or choose the order/tracking option."
4. When recommending products, give at most 3 options and a one-line reason for each.
5. Use simple bullet points where helpful.
""",
tools=[save_cart],
sub_agents=[checkout_agent]
)