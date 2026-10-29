"""
utils.py — instrumented agent code shared by the evaluation labs (L7, L9, L11).

This is the exact agent from L5.py (Lab 2 - Tracing) extracted into a module so
L7 (Router & Skill Evaluations), L9 (Trajectory Evaluations) and L11 (Overall
/ Structured Evaluations) can import and drive it:
    from utils import run_agent, start_main_span, tools, get_phoenix_endpoint
    from utils import process_messages, update_sql_gen_prompt, get_sql_gen_prompt

Configuration comes from .env (OLLAMA_API_KEY / OLLAMA_BASE_URL / OLLAMA_MODEL / PHOENIX_ENDPOINT).
"""

from openai import OpenAI
import pandas as pd
import json
import duckdb
from pydantic import BaseModel, Field

from dotenv import load_dotenv
import os
import re
import sys
import warnings
warnings.filterwarnings('ignore')

# Windows console fix: force UTF-8 so LLM output with Unicode chars never breaks print()
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load configuration from .env file in this folder
load_dotenv()

openai_api_key = os.getenv("OLLAMA_API_KEY", "")
openai_base_url = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")

if not openai_api_key:
    raise RuntimeError(
        "OLLAMA_API_KEY is not set. "
        "Add it to the .env file next to utils.py "
        "(create a key at https://ollama.com/settings/keys)."
    )

# Ollama Cloud exposes an OpenAI-compatible API, so the standard OpenAI client works
client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)

MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")

# ------------------------------------------------------------------
# Phoenix tracing setup (local Phoenix server, auto-started)
# ------------------------------------------------------------------

import time
import urllib.request
import subprocess

import phoenix as px
from phoenix.otel import register
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.trace import Status, StatusCode


def get_phoenix_endpoint() -> str:
    """Base URL of the (local) Phoenix server, from env or default localhost:6006"""
    return os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006").rstrip("/") + "/"


def _phoenix_ready(base: str, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "healthz", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def ensure_phoenix_running():
    """Start the local Phoenix server if it is not already running (UI: http://localhost:6006)."""
    base = get_phoenix_endpoint()
    if _phoenix_ready(base, timeout_s=3):
        print(f"Phoenix already running at {base}")
        return
    print(f"Starting local Phoenix server (UI: {base})...")
    subprocess.Popen(
        [sys.executable, "-m", "phoenix.server.main", "serve"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not _phoenix_ready(base, timeout_s=90):
        print("WARNING: Phoenix server did not come up in time; traces may not be visible.")


PROJECT_NAME = "evaluating-agent"

ensure_phoenix_running()

tracer_provider = register(
    project_name=PROJECT_NAME,
    endpoint=get_phoenix_endpoint() + "v1/traces"
)

OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

tracer = tracer_provider.get_tracer(__name__)


# ------------------------------------------------------------------
# Tools (identical logic to L3/L5)
# ------------------------------------------------------------------

TRANSACTION_DATA_FILE_PATH = 'data/Store_Sales_Price_Elasticity_Promotions_Data.parquet'

SQL_GENERATION_PROMPT = """
Generate an SQL query based on a prompt. Do not reply with anything besides the SQL query.
The prompt is: {prompt}

The available columns are: {columns}
The table name is: {table_name}
"""


def generate_sql_query(prompt: str, columns: list, table_name: str) -> str:
    """Generate an SQL query based on a prompt"""
    formatted_prompt = SQL_GENERATION_PROMPT.format(prompt=prompt,
                                                    columns=columns,
                                                    table_name=table_name)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": formatted_prompt}],
    )

    return response.choices[0].message.content


@tracer.tool()
def lookup_sales_data(prompt: str) -> str:
    """Implementation of sales data lookup from parquet file using SQL"""
    try:
        table_name = "sales"

        # step 1: read the parquet file into a DuckDB table
        df = pd.read_parquet(TRANSACTION_DATA_FILE_PATH)
        duckdb.sql(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df")

        # step 2: generate the SQL code
        sql_query = generate_sql_query(prompt, list(df.columns), table_name)
        sql_query = sql_query.strip()
        sql_query = sql_query.replace("```sql", "").replace("```", "")

        with tracer.start_as_current_span(
            "execute_sql_query",
            openinference_span_kind="chain"
        ) as span:
            span.set_input(sql_query)
            # step 3: execute the SQL query
            result = duckdb.sql(sql_query).df()
            span.set_output(value=str(result))
            span.set_status(StatusCode.OK)

        return result.to_string()
    except Exception as e:
        return f"Error accessing data: {str(e)}"


DATA_ANALYSIS_PROMPT = """
Analyze the following data: {data}
Your job is to answer the following question: {prompt}
"""


@tracer.tool()
def analyze_sales_data(prompt: str, data: str) -> str:
    """Implementation of AI-powered sales data analysis"""
    formatted_prompt = DATA_ANALYSIS_PROMPT.format(data=data, prompt=prompt)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": formatted_prompt}],
    )

    analysis = response.choices[0].message.content
    return analysis if analysis else "No analysis could be generated"


CHART_CONFIGURATION_PROMPT = """
Generate a chart configuration based on this data: {data}
The goal is to show: {visualization_goal}
"""


class VisualizationConfig(BaseModel):
    chart_type: str = Field(..., description="Type of chart to generate")
    x_axis: str = Field(..., description="Name of the x-axis column")
    y_axis: str = Field(..., description="Name of the y-axis column")
    title: str = Field(..., description="Title of the chart")


@tracer.chain()
def extract_chart_config(data: str, visualization_goal: str) -> dict:
    """Generate chart visualization configuration"""
    formatted_prompt = CHART_CONFIGURATION_PROMPT.format(data=data,
                                                         visualization_goal=visualization_goal)
    formatted_prompt += ("\n\nYou MUST respond with ONLY a single JSON object (no markdown fences, no extra text) "
                         "with exactly these keys: chart_type, x_axis, y_axis, title.")

    # Ollama Cloud does not support OpenAI's beta structured-outputs parse() endpoint,
    # but it does support JSON mode on /v1/chat/completions
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": formatted_prompt}],
            response_format={"type": "json_object"},
        )
    except Exception:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": formatted_prompt}],
        )

    try:
        content = (response.choices[0].message.content or "").strip()
        content = content.replace("```json", "").replace("```", "")

        if not content.startswith("{"):
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                content = match.group(0)

        config = VisualizationConfig.model_validate_json(content)

        return {
            "chart_type": config.chart_type,
            "x_axis": config.x_axis,
            "y_axis": config.y_axis,
            "title": config.title,
            "data": data
        }
    except Exception:
        return {
            "chart_type": "line",
            "x_axis": "date",
            "y_axis": "value",
            "title": visualization_goal,
            "data": data
        }


CREATE_CHART_PROMPT = """
Write python code to create a chart based on the following configuration.
Only return the code, no other text.
config: {config}
"""


@tracer.chain()
def create_chart(config: dict) -> str:
    """Create a chart based on the configuration"""
    formatted_prompt = CREATE_CHART_PROMPT.format(config=config)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": formatted_prompt}],
    )

    code = response.choices[0].message.content
    code = code.replace("```python", "").replace("```", "")
    code = code.strip()

    return code


@tracer.tool()
def generate_visualization(data: str, visualization_goal: str) -> str:
    """Generate a visualization based on the data and goal"""
    config = extract_chart_config(data, visualization_goal)
    code = create_chart(config)
    return code


# ------------------------------------------------------------------
# Tool schema (identical to L3/L5)
# ------------------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "lookup_sales_data",
            "description": "Look up data from Store Sales Price Elasticity Promotions dataset",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The unchanged prompt that the user provided."}
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_sales_data",
            "description": "Analyze sales data to extract insights",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "The lookup_sales_data tool's output."},
                    "prompt": {"type": "string", "description": "The unchanged prompt that the user provided."}
                },
                "required": ["data", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_visualization",
            "description": "Generate Python code to create data visualizations",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "The lookup_sales_data tool's output."},
                    "visualization_goal": {"type": "string", "description": "The goal of the visualization."}
                },
                "required": ["data", "visualization_goal"]
            }
        }
    }
]

tool_implementations = {
    "lookup_sales_data": lookup_sales_data,
    "analyze_sales_data": analyze_sales_data,
    "generate_visualization": generate_visualization
}


def handle_tool_calls(tool_calls, messages):
    for tool_call in tool_calls:
        function = tool_implementations[tool_call.function.name]
        function_args = json.loads(tool_call.function.arguments)
        result = function(**function_args)
        messages.append({"role": "tool",
                         "content": result,
                         "tool_call_id": tool_call.id})
    return messages


SYSTEM_PROMPT = """
You are a helpful assistant that can answer questions about the Store Sales Price Elasticity Promotions dataset.
"""


def run_agent(messages):
    print("Running agent with messages:", messages)
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    if not any(
            isinstance(message, dict) and message.get("role") == "system" for message in messages
    ):
        system_prompt = {"role": "system", "content": SYSTEM_PROMPT}
        messages.append(system_prompt)

    while True:
        # Router Span
        print("Starting router call span")
        with tracer.start_as_current_span(
            "router_call", openinference_span_kind="chain",
        ) as span:
            span.set_input(value=messages)

            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
            )
            messages.append(response.choices[0].message.model_dump())
            tool_calls = response.choices[0].message.tool_calls
            print("Received response with tool calls:", bool(tool_calls))
            span.set_status(StatusCode.OK)

            if tool_calls:
                print("Starting tool calls span")
                messages = handle_tool_calls(tool_calls, messages)
                span.set_output(value=tool_calls)
            else:
                print("No tool calls, returning final response")
                span.set_output(value=response.choices[0].message.content)
                return response.choices[0].message.content


def start_main_span(messages):
    print("Starting main span with messages:", messages)

    with tracer.start_as_current_span(
        "AgentRun", openinference_span_kind="agent"
    ) as span:
        span.set_input(value=messages)
        ret = run_agent(messages)
        print("Main span completed")
        span.set_output(value=ret)
        span.set_status(StatusCode.OK)
        return ret


# ------------------------------------------------------------------
# Helpers for L11 (Overall Experiment). run_agent() returns only the final
# answer string but appends every message to `messages` in place — that list
# IS the full agent trajectory (user, system, assistant tool-call turns, tool
# responses, final answer), so post-process it for the per-tool evaluators.
# ------------------------------------------------------------------

def process_messages(messages):
    """Summarize an agent message list the way the course notebook did."""
    # ponytail: dict-keyed tool responses (original matched by tool_call_id inside a
    # shadowed `message` var — buggy); keying by id is the same intent, actually correct.
    tool_calls = []
    tool_responses = []
    final_output = None
    response_by_call_id = {}

    for message in messages:
        if isinstance(message, dict) and message.get("role") == "assistant" and message.get("tool_calls"):
            for tool_call in message["tool_calls"]:
                tool_calls.append(tool_call["function"]["name"])
                tool_responses.append({
                    "tool_name": tool_call["function"]["name"],
                    "tool_input": tool_call["function"]["arguments"],
                    "tool_response": None,
                })
        elif isinstance(message, dict) and message.get("role") == "tool":
            response_by_call_id[message.get("tool_call_id")] = message.get("content")
        elif isinstance(message, dict) and message.get("role") == "assistant":
            final_output = message.get("content")

    # assistant tool-call turns are plain dicts after model_dump(); tool messages
    # reference them by tool_call_id
    tool_call_ids = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "assistant" and message.get("tool_calls"):
            tool_call_ids.extend(tc.get("id") for tc in message["tool_calls"])
    for response, call_id in zip(tool_responses, tool_call_ids):
        if response["tool_response"] is None:
            response["tool_response"] = response_by_call_id.get(call_id)

    return {
        "tool_calls": tool_calls,
        "tool_responses": tool_responses,
        "final_output": final_output,
        "unchanged_messages": messages,
        "path_length": len(messages),
    }


def update_sql_gen_prompt(new_prompt: str):
    """Replace the SQL-generation system prompt used by lookup_sales_data (L11 v2 experiment)."""
    # ponytail: module-level global, matches the original course notebook's behavior
    global SQL_GENERATION_PROMPT
    SQL_GENERATION_PROMPT = new_prompt


def get_sql_gen_prompt() -> str:
    """Current SQL-generation prompt (L11 playground section prints this)."""
    return SQL_GENERATION_PROMPT