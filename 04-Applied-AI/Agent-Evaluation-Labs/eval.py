#!/usr/bin/env python
# coding: utf-8

"""
eval.py — all five labs in one file (consolidates backup/L3,L5,L7,L9,L11).

The agent itself (tools, router, tracing setup, prompt helpers) stays in utils.py.
This file is only the OBSERVATION + EVALUATION harness:

    python eval.py 3     # Lab 1: run the agent on a question (interactive)
    python eval.py 5     # Lab 2: tracing demo (spans visible in Phoenix UI)
    python eval.py 7     # Lab 3: router & skill evals (span queries + LLM judges)
    python eval.py 9     # Lab 4: trajectory/convergence eval (Phoenix experiment)
    python eval.py 11    # Lab 5: overall eval (5 evaluators + SQL-prompt-change rerun)
    python eval.py all   # run 3 -> 11 sequentially

Env config (.env): OLLAMA_API_KEY / OLLAMA_BASE_URL / OLLAMA_MODEL / PHOENIX_ENDPOINT.
"""

import warnings
warnings.filterwarnings('ignore')

import json
import os
import re
import sys
import time
import urllib.request

import pandas as pd

# Windows console fix: force UTF-8 so LLM output with Unicode chars never breaks print()
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")  # non-interactive backend; plt.show() in generated code is a no-op

from openinference.instrumentation import suppress_tracing
from phoenix.trace.dsl import SpanQuery
from phoenix.client import Client as PhoenixClient
# ponytail: phoenix.experiments.evaluators.create_evaluator moved here in phoenix 20.x
from phoenix.client.resources.experiments.evaluators import create_evaluator

# Importing utils starts the local Phoenix server, registers tracing, and instruments
# OpenAI calls (the agent: same code as backup/L5.py, project "evaluating-agent").
from utils import (get_phoenix_endpoint, run_agent, start_main_span, tools,
                   process_messages, update_sql_gen_prompt, get_sql_gen_prompt)

PROJECT_NAME = "evaluating-agent"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

PHOENIX_CLIENT = PhoenixClient(base_url=get_phoenix_endpoint().rstrip("/") + "/")
run_experiment = PHOENIX_CLIENT.experiments.run_experiment
evaluate_experiment = PHOENIX_CLIENT.experiments.evaluate_experiment

DEFAULT_SQL_PROMPT = get_sql_gen_prompt()  # restored between labs (lab11 mutates it)

NEW_SQL_PROMPT = """
Generate an SQL query based on a prompt.
Do not reply with anything besides the SQL query.
The prompt is: {prompt}

The available columns are: {columns}
The table name is: {table_name}

Think before you respond.
"""


# ======================================================================
# Shared LLM-as-a-Judge plumbing (Ollama Cloud via raw HTTP, JSON mode)
#
# Replaces the removed phoenix.evals API (OpenAIModel / llm_classify).
# Ollama Cloud rejects structured-output json_schema and forced tool calls
# (verified), so the judge speaks plain JSON-mode chat. Raw HTTP keeps judge
# calls un-instrumented so they never leak into Phoenix traces as root
# ChatCompletion spans. suppress_tracing() is belt-and-braces inside run_judge.
# ======================================================================

_JUDGE_URL = OLLAMA_BASE_URL.rstrip("/") + "/chat/completions"
_JUDGE_HEADERS = {"Content-Type": "application/json",
                  "Authorization": f"Bearer {OLLAMA_API_KEY}"}


def _judge_request(payload: dict) -> str:
    req = urllib.request.Request(
        _JUDGE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=_JUDGE_HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def run_judge(prompt: str, rails: list, default_label: str = None) -> dict:
    """One LLM-as-a-judge call via Ollama Cloud JSON mode.

    Returns {"label": <rail>, "explanation": <str>}. Unparseable replies fall
    back to default_label (or the last rail) — callers pick the failure default.
    """
    with suppress_tracing():
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        try:
            content = _judge_request(payload)
        except Exception:
            # Fallback: JSON mode rejected; retry once as plain chat
            content = _judge_request({"model": OLLAMA_MODEL,
                                      "messages": [{"role": "user", "content": prompt}]})
    content = content.replace("```json", "").replace("```", "")
    if not content.startswith("{"):
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            content = m.group(0)
    try:
        parsed = json.loads(content)
        label = str(parsed.get("label", "")).strip().strip('"').lower()
        explanation = str(parsed.get("explanation", content))
    except Exception:
        # Last resort: search for a bare rail word in the raw text
        label = ""
        for rail in rails:
            if rail.lower() in content.lower():
                label = rail.lower()
                break
        explanation = content
    label = label if label in rails else (default_label or rails[-1])
    return {"label": label, "explanation": explanation}


def judge_dataframe(df: pd.DataFrame, template: str, rails: list,
                    default_label: str = None) -> pd.DataFrame:
    """row-wise run_judge over a span-query dataframe; adds label/score/explanation."""
    labels, explanations = [], []
    for _, row in df.iterrows():
        try:
            result = run_judge(template.format(**row.to_dict()), rails, default_label)
        except Exception as e:
            result = {"label": default_label or rails[-1], "explanation": f"judge error: {e}"}
        labels.append(result["label"])
        explanations.append(result["explanation"])
    out = df.copy()
    out["label"] = labels
    out["explanation"] = explanations
    out["score"] = out["label"].map({r: 1 if i == 0 else 0 for i, r in enumerate(rails)})
    return out


def log_span_evaluations(eval_name: str, df: pd.DataFrame):
    """Log label/score/explanation per span_id to Phoenix (non-blocking upload)."""
    annotations = pd.DataFrame({
        "span_id": df.index.astype(str),
        "annotation_name": eval_name,
        "annotator_kind": "LLM",
        "label": df["label"],
        "score": df["score"].astype(float),
        "explanation": df["explanation"],
    }).dropna(subset=["span_id"])
    PHOENIX_CLIENT.spans.log_span_annotations_dataframe(
        dataframe=annotations, annotator_kind="LLM", annotation_name=eval_name, sync=False
    )
    print(f"Logged {len(annotations)} '{eval_name}' annotations to Phoenix", flush=True)
    print_ui_scores(eval_name, df.assign(name=eval_name))


def get_or_create_dataset(prefix: str, df: pd.DataFrame,
                          output_keys: list = None):
    """Upload a dataset once; reuse it on re-runs (no duplicate stacking)."""
    existing = [d for d in PHOENIX_CLIENT.datasets.list()
                if d["name"].startswith(prefix)]
    if existing:
        ds = PHOENIX_CLIENT.datasets.get_dataset(dataset=existing[-1]["id"])
        print(f"Reusing existing dataset '{ds.name}' ({ds.example_count} examples)")
        return ds
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    ds = PHOENIX_CLIENT.datasets.create_dataset(
        dataframe=df, name=f"{prefix}-{now}", input_keys=["question"],
        output_keys=output_keys or [])
    print(f"Created dataset '{ds.name}' ({ds.example_count} examples)")
    return ds


def evals_to_df(experiment):
    """Score table from a (Ran)Experiment's evaluation_runs."""
    df = pd.DataFrame([{"name": er.name,
                        "score": (er.result or {}).get("score"),
                        "label": (er.result or {}).get("label"),
                        "explanation": (er.result or {}).get("explanation")}
                       for er in experiment["evaluation_runs"]])
    return df


def print_ui_scores(title: str, df: pd.DataFrame):
    rows = []
    for name, group in df.groupby("name"):
        scores = pd.to_numeric(group["score"], errors="coerce")
        rows.append({"evaluator": name, "passed": int(scores.eq(1).sum()),
                     "total": len(group), "score": float(scores.mean()) if scores.notna().any() else None})
    print("__EVAL_UI__" + json.dumps({"title": title, "scores": rows}), flush=True)


def print_experiment_summary(evals_df: pd.DataFrame, title: str = "Convergence evaluation"):
    print(evals_df.to_string())
    if len(evals_df):
        print("\nAverage per evaluator:")
        print(evals_df.groupby("name")["score"].mean().to_string())
        print_ui_scores(title, evals_df)


# ======================================================================
# Lab 3 (course Lab 1): Building your Agent — one question, interactive
# ======================================================================

def lab3():
    """Interactive agent. Ask questions; chart code in answers is executed
    (Agg backend) and saved to chart.png. 'exit' quits."""
    import matplotlib.pyplot as plt

    print(f"Agent ready (model: {OLLAMA_MODEL}). Phoenix UI: {get_phoenix_endpoint()}")
    try:
        while True:
            try:
                user_question = input("\nAsk a question about the sales data (or 'exit' to quit): ").strip()
            except EOFError:
                break
            if not user_question:
                continue
            if user_question.lower() in ("exit", "quit", "q"):
                break
            result = run_agent(user_question)
            print("\n" + "=" * 60 + f"\nANSWER:\n{result}\n" + "=" * 60)
            chart_match = re.search(r"```python\s*\n(.*?)```", result or "", re.DOTALL)
            if chart_match and ("plt." in chart_match.group(1) or "matplotlib" in chart_match.group(1)):
                try:
                    ns = {}
                    exec(chart_match.group(1), ns)
                    (ns.get("fig") or plt.gcf()).savefig("chart.png", dpi=150, bbox_inches="tight")
                    plt.close("all")
                    print("Chart saved to chart.png")
                except Exception as e:
                    print(f"(Generated chart code could not be auto-executed: {e})")
    except KeyboardInterrupt:
        pass
    print("Bye!")


# ======================================================================
# Lab 5 (course Lab 2): Tracing your Agent — demo questions, spans in UI
# ======================================================================

def lab5():
    """Run the traced agent on demo questions; inspect spans in Phoenix UI.

    Every lab5 question runs under start_main_span (AgentRun -> router_call
    chains -> tool spans -> nested LLM spans) and lands in project
    "evaluating-agent" in the Phoenix UI."""
    print(f"Running traced demo questions. Phoenix UI: {get_phoenix_endpoint()}")
    for question in [
        "What was the most popular product SKU?",
        "Which stores did the best in 2021?",
    ]:
        try:
            result = start_main_span([{"role": "user", "content": question}])
            print("\nQ:", question)
            print("A:", result)
        except Exception as e:
            print(f"Error processing question: {question}")
            print(e)
    time.sleep(5)  # let Phoenix index the just-finished spans
    print(f"\nPhoenix UI: {get_phoenix_endpoint()}  (project: {PROJECT_NAME})")


# ======================================================================
# Lab 7 (course Lab 3): Router & Skill Evaluations (span queries + judges)
# ======================================================================

TOOL_CALLING_PROMPT_TEMPLATE = """In this task, you will be presented with a list of tools available to an AI assistant,
the question the user asked, and the assistant's actual response — including any tool
calls it decided to make (function name + arguments). Your objective is to evaluate whether
the assistant chose the correct tool(s) and extracted the correct parameter values,
given the tool definitions below.

Tool definitions:
{tool_definitions}

[BEGIN DATA]
Query: {question}
Response (assistant output with tool calls): {tool_call}
[END DATA]

The available labels are:
- "correct": the tool choice and extracted parameters are appropriate for answering the query
- "incorrect": the tool choice or parameter values are wrong or missing

Respond ONLY with a JSON object in this exact shape, with no other text, comments, or markdown:
{{"explanation": "<your detailed reasoning, never starting with the label>", "label": "correct" or "incorrect"}}
"""


CLARITY_LLM_JUDGE_PROMPT = """You will be presented with a query and an answer. Evaluate the clarity
of the answer in addressing the query. A clear response is precise, coherent, and directly
addresses the query without unnecessary complexity or ambiguity. An unclear response is vague,
disorganized, or difficult to understand, even if factually correct.

[BEGIN DATA]
Query: {query}
Answer: {response}
[END DATA]

Respond ONLY with a JSON object in this exact shape, with no other text, comments, or markdown:
{{"explanation": "<your detailed reasoning, never starting with the label>", "label": "clear" or "unclear"}}
"""

SQL_EVAL_GEN_PROMPT = """You are tasked with determining if the SQL generated appropriately answers a given instruction.

Data:
- [Instruction]: {question}
- [Reference Query]: {query_gen}

Evaluation:
- "correct" indicates the SQL query correctly solves the instruction.
- "incorrect" indicates it does not.

Respond ONLY with a JSON object in this exact shape, with no other text, comments, or markdown:
{{"explanation": "<your detailed reasoning, never starting with the label>", "label": "correct" or "incorrect"}}
"""


def lab7():
    """Run 6 test questions, then judge their spans: router tool-choice,
    chart-code runnability, analysis clarity, SQL gen."""
    from tqdm import tqdm

    update_sql_gen_prompt(DEFAULT_SQL_PROMPT)  # fresh state each lab run

    agent_questions = [
        "What was the most popular product SKU?",
        "What was the total revenue across all stores?",
        "Which store had the highest sales volume?",
        "Create a bar chart showing total sales by store",
        "What percentage of items were sold on promotion?",
        "What was the average transaction value?",
    ]
    print(f"\nRunning agent on {len(agent_questions)} test questions (traced to Phoenix)...")
    for question in tqdm(agent_questions, desc="Processing questions"):
        try:
            start_main_span([{"role": "user", "content": question}])
        except Exception as e:
            print(f"Error processing question: {question}")
            print(e)
    time.sleep(5)

    # -- Router eval: judge the ASSISTANT'S ACTUAL OUTPUT (real tool calls), not
    # the static tool-schema list (judging the schema caused false 'incorrect').
    tool_calls_df = PHOENIX_CLIENT.spans.get_spans_dataframe(
        query=SpanQuery().where("span_kind == 'LLM'").select(
            question="input.value", tool_call="llm.output_messages"),
        project_name=PROJECT_NAME, timeout=None)
    tool_calls_df = tool_calls_df[
        tool_calls_df["tool_call"].astype(str).str.contains("tool_calls", regex=False)]
    print(f"\nFound {len(tool_calls_df)} LLM spans with real tool calls", flush=True)

    if len(tool_calls_df):
        try:
            safe_tool_defs = json.dumps(tools).replace("{", "'").replace("}", "'")
            template = TOOL_CALLING_PROMPT_TEMPLATE.replace("{tool_definitions}", safe_tool_defs)
            eval_df = judge_dataframe(tool_calls_df, template, rails=["correct", "incorrect"])
            print(eval_df[["label", "score"]].head())
            log_span_evaluations("Tool Calling Eval", eval_df)
        except Exception as e:
            print(f"Tool Calling Eval FAILED (continuing): {e}", flush=True)

    # -- Chart code gen eval (tool 3)
    code_gen_df = PHOENIX_CLIENT.spans.get_spans_dataframe(
        query=SpanQuery().where("name == 'generate_visualization'").select(
            generated_code="output.value"),
        project_name=PROJECT_NAME, timeout=None)
    print(f"\nFound {len(code_gen_df)} generate_visualization spans", flush=True)

    def code_is_runnable(output: str) -> bool:
        output = str(output).strip().replace("```python", "").replace("```", "")
        try:
            with suppress_tracing():
                exec(output)
            return True
        except Exception:
            return False

    if len(code_gen_df):
        code_gen_df["label"] = code_gen_df["generated_code"].apply(code_is_runnable).map(
            {True: "runnable", False: "not_runnable"})
        code_gen_df["score"] = code_gen_df["label"].map({"runnable": 1, "not_runnable": 0})
        code_gen_df["explanation"] = "code-based eval: exec() of generated code"
        print(code_gen_df[["label", "score"]].head())
        log_span_evaluations("Runnable Code Eval", code_gen_df)

    # -- Clarity eval (tool 2)
    clarity_df = PHOENIX_CLIENT.spans.get_spans_dataframe(
        query=SpanQuery().where("span_kind == 'AGENT'").select(
            response="output.value", query="input.value"),
        project_name=PROJECT_NAME, timeout=None)
    print(f"\nFound {len(clarity_df)} AGENT spans for clarity evaluation", flush=True)
    if len(clarity_df):
        try:
            clarity_eval = judge_dataframe(clarity_df, CLARITY_LLM_JUDGE_PROMPT,
                                           rails=["clear", "unclear"])
            print(clarity_eval[["label", "score"]].head())
            log_span_evaluations("Response Clarity", clarity_eval)
        except Exception as e:
            print(f"Response Clarity eval FAILED (continuing): {e}", flush=True)

    # -- SQL gen eval (tool 1)
    sql_df = PHOENIX_CLIENT.spans.get_spans_dataframe(
        query=SpanQuery().where("span_kind == 'LLM'").select(
            query_gen="llm.output_messages", question="input.value"),
        project_name=PROJECT_NAME, timeout=None)
    if len(sql_df):
        sql_df = sql_df[sql_df["question"].astype(str).str.contains(
            "Generate an SQL query based on a prompt.", na=False)]
    print(f"\nFound {len(sql_df)} SQL generation spans", flush=True)
    if len(sql_df):
        try:
            sql_gen_eval = judge_dataframe(sql_df, SQL_EVAL_GEN_PROMPT,
                                           rails=["correct", "incorrect"])
            print(sql_gen_eval[["label", "score"]].head())
            log_span_evaluations("SQL Gen Eval", sql_gen_eval)
        except Exception as e:
            print(f"SQL Gen Eval FAILED (continuing): {e}", flush=True)

    print("\n" + "=" * 60)
    print("EVALUATION RUN COMPLETE")
    print("=" * 60)
    print(f"Phoenix UI: {get_phoenix_endpoint()}")
    print(f"Project:    {PROJECT_NAME}")
    print("Open a span in the Phoenix UI -> 'Annotations' to see the")
    print("Tool Calling / Runnable Code / Response Clarity / SQL Gen results.")


# ======================================================================
# Lab 9 (course Lab 4): Trajectory/Convergence Evaluation (experiment)
# ======================================================================

def format_message_steps(messages):
    """Readable step list from the agent message trajectory."""
    steps = []
    for message in messages:
        role = message.get("role")
        if role == "user":
            steps.append(f"User: {message.get('content')}")
        elif role == "system":
            steps.append("System: Provided context")
        elif role == "assistant":
            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    steps.append(f"Assistant: Called tool '{tool_call['function']['name']}'")
            else:
                steps.append(f"Assistant: {message.get('content')}")
        elif role == "tool":
            steps.append(f"Tool response: {message.get('content')}")
    return "\n".join(steps)


def run_agent_and_track_path(example):
    # utils.run_agent returns only the final answer string but appends every
    # message to `messages` in place — that list IS the agent's path.
    messages = [{"role": "user", "content": example.input.get("question")}]
    run_agent(messages)
    return {"path_length": len(messages), "messages": format_message_steps(messages)}


def lab9():
    """Convergence score: 17 paraphrases of one question; path-length evaluator."""
    update_sql_gen_prompt(DEFAULT_SQL_PROMPT)

    convergence_questions = [
        "What was the average quantity sold per transaction?",
        "What is the mean number of items per sale?",
        "Calculate the typical quantity per transaction",
        "What's the mean transaction size in terms of quantity?",
        "On average, how many items were purchased per transaction?",
        "What is the average basket size per sale?",
        "Calculate the mean number of products per purchase",
        "What's the typical number of units per order?",
        "What is the average number of products bought per purchase?",
        "Tell me the mean quantity of items in a typical transaction",
        "How many items does a customer buy on average per transaction?",
        "What's the usual number of units in each sale?",
        "What is the typical amount of products per transaction?",
        "Show the mean number of items customers purchase per visit",
        "What's the average quantity of units per shopping trip?",
        "How many products do customers typically buy in one transaction?",
        "What is the standard basket size in terms of quantity?",
    ]
    dataset = get_or_create_dataset("convergence_questions",
                                    pd.DataFrame({"question": convergence_questions}))

    print(f"\nPhoenix UI: {get_phoenix_endpoint()}")
    # timeout=120: Ollama Cloud agent turns take ~10-20s each (3+ LLM calls per
    # question); the default 60s HTTP timeout is too tight.
    experiment = run_experiment(dataset=dataset,
                                task=run_agent_and_track_path,
                                evaluators=None,
                                experiment_name="Convergence Eval",
                                experiment_description="Evaluating the convergence of the agent",
                                timeout=120)

    print(pd.DataFrame(experiment["task_runs"])[["dataset_example_id", "output", "error"]].to_string())

    outputs = [run.get("output") for run in experiment["task_runs"]]
    optimal_path_length = min(o.get("path_length") for o in outputs
                              if o and o.get("path_length") is not None)
    print(f"\nThe optimal path length is {optimal_path_length}")

    @create_evaluator(name="Convergence Eval", kind="CODE")
    def evaluate_path_length(output) -> float:
        if output and output.get("path_length"):
            return optimal_path_length / float(output.get("path_length"))
        return 0

    experiment = evaluate_experiment(experiment=experiment,
                                     evaluators=[evaluate_path_length],
                                     timeout=120)
    print_experiment_summary(evals_to_df(experiment))
    print(f"\nAverage convergence score: "
          f"{evals_to_df(experiment)['score'].mean():.4f}")
    print(f"Phoenix UI: {get_phoenix_endpoint()}  (project: {PROJECT_NAME})")
    print("Experiments view (dataset page) shows the 'Convergence Eval' run + scores.")


# ======================================================================
# Lab 11 (course Lab 5): Overall/Structured Evaluation (5 evaluators)
# ======================================================================

def _make_overall_evaluators():
    """The five evaluators. LLM judges close over nothing mutable; the router
    prompt embeds tool JSON via .replace() (placeholders inside JSON examples
    would break str.format, and Ollama Cloud needs an explicit JSON-reply shape
    plus a first-step scope note or it marks lookup_sales_data 'incorrect')."""

    TOOL_TEMPLATE = """In this task, you will be presented with a list of tools available to an AI assistant,
the question the user asked, and the assistant's actual response — including any tool
calls it decided to make (function names). Your objective is to evaluate whether
the assistant chose the correct tool(s) to answer the query, given the tool definitions below.

Tool definitions:
{tool_definitions}

[BEGIN DATA]
Query: {question}
Response (assistant output with tool calls): {tool_call}
[END DATA]

The available labels are:
- "correct": the tool choice is appropriate for answering the query
- "incorrect": the tool choice is wrong or missing

Respond ONLY with a JSON object in this exact shape, with no other text, comments, or markdown:
{{"explanation": "<your detailed reasoning, never starting with the label>", "label": "correct" or "incorrect"}}

IMPORTANT: lookup_sales_data is the correct and expected first tool for ANY question
about sales metrics (totals, averages, percentages, rankings, chart data). Calling it
means the tool choice is "correct". Mark "incorrect" ONLY when the called tool cannot
contribute to answering the query at all.
"""

    @create_evaluator(kind="LLM", name="function_calling_eval")
    def function_calling_eval(input, output) -> float:
        if output is None:
            return 0
        function_calls = output.get("tool_calls")
        if function_calls:
            prompt = (TOOL_TEMPLATE
                      .replace("{tool_definitions}", json.dumps(tools).replace("{", '"').replace("}", '"'))
                      .replace("{question}", str(input.get("question")))
                      .replace("{tool_call}", json.dumps(function_calls)))
            result = run_judge(prompt, rails=["correct", "incorrect"], default_label="incorrect")
            return 1.0 if result["label"] == "correct" else 0.0
        return 0

    @create_evaluator(kind="CODE", name="evaluate_sql_result")
    def evaluate_sql_result(output, expected) -> bool:
        if output is None:
            return False
        tool_responses = output.get("tool_responses")
        if not tool_responses:
            return True
        sql_result = next((r for r in tool_responses
                           if r.get("tool_name") == "lookup_sales_data"), None)
        if not sql_result:
            return True
        sql_result = sql_result.get("tool_response", "") or ""
        # course semantics: exact digit-concatenation match against the expected result
        result_nums = ''.join(filter(str.isdigit, str(sql_result)))
        expected_val = expected.get("sql_result", "") if isinstance(expected, dict) else ""
        expected_nums = ''.join(filter(str.isdigit, str(expected_val)))
        return result_nums == expected_nums

    CLARITY_PROMPT = """In this task, you will be presented with a query and an answer. Your objective is to evaluate the clarity
of the answer in addressing the query. A clear response is one that is precise, coherent, and directly
addresses the query without introducing unnecessary complexity or ambiguity. An unclear response is one
that is vague, disorganized, or difficult to understand, even if it may be factually correct.

A "clear" answer is well-structured, easy to understand, and appropriately addresses the query.
An "unclear" answer is ambiguous, poorly organized, or not effectively communicated.

[BEGIN DATA]
Query: {query}
Answer: {response}
[END DATA]

Respond ONLY with a JSON object in this exact shape, with no other text, comments, or markdown:
{{"explanation": "<your detailed reasoning, never starting with the label>", "label": "clear" or "unclear"}}
"""

    @create_evaluator(kind="LLM", name="evaluate_clarity")
    def evaluate_clarity(output, input) -> bool:
        if output is None:
            return False
        prompt = (CLARITY_PROMPT
                  .replace("{query}", str(input.get("question")))
                  .replace("{response}", str(output.get("final_output"))))
        return run_judge(prompt, rails=["clear", "unclear"],
                         default_label="unclear")["label"] == "clear"

    ENTITY_PROMPT = """In this task, you will be presented with a query and an answer. Your objective is to determine whether all
the entities mentioned in the answer are correctly identified and accurately match those in the query. An
entity refers to any specific person, place, organization, date, or other proper noun. Your evaluation
should focus on whether the entities in the answer are correctly named and appropriately associated with
the context in the query.

A "correct" answer contains no errors or mismatches in the entities referenced compared to the query.
An "incorrect" answer contains errors or mismatches in the entities referenced.

[BEGIN DATA]
Query: {query}
Answer: {response}
[END DATA]

Respond ONLY with a JSON object in this exact shape, with no other text, comments, or markdown:
{{"explanation": "<your detailed reasoning, never starting with the label>", "label": "correct" or "incorrect"}}
"""

    @create_evaluator(kind="LLM", name="evaluate_entity_correctness")
    def evaluate_entity_correctness(output, input) -> bool:
        if output is None:
            return False
        prompt = (ENTITY_PROMPT
                  .replace("{query}", str(input.get("question")))
                  .replace("{response}", str(output.get("final_output"))))
        return run_judge(prompt, rails=["correct", "incorrect"],
                         default_label="incorrect")["label"] == "correct"

    @create_evaluator(kind="CODE", name="code_is_runnable")
    def code_is_runnable(output) -> bool:
        if output is None:
            return False
        tool_responses = output.get("tool_responses")
        if not tool_responses:
            return True
        viz = next((r for r in tool_responses
                    if r.get("tool_name") == "generate_visualization"), None)
        if not viz:
            return True
        code = str(viz.get("tool_response") or "").strip()
        code = code.replace("```python", "").replace("```", "")
        if not code:
            return False
        try:
            exec(code)
            return True
        except Exception:
            return False

    return [function_calling_eval, evaluate_sql_result, evaluate_clarity,
            evaluate_entity_correctness, code_is_runnable]


OVERALL_QUESTIONS = [
    {'question': 'What was the most popular product SKU?',
     'sql_result': '   SKU_Coded  Total_Qty_Sold 0    6200700         52262.0',
     'sql_generated': '```sql\nSELECT SKU_Coded, SUM(Qty_Sold) AS Total_Qty_Sold\nFROM sales\nGROUP BY SKU_Coded\nORDER BY Total_Qty_Sold DESC\nLIMIT 1;\n```'},
    {'question': 'What was the total revenue across all stores?',
     'sql_result': '   Total_Revenue 0   1.327264e+07',
     'sql_generated': '```sql\nSELECT SUM(Total_Sale_Value) AS Total_Revenue\nFROM sales;\n```'},
    {'question': 'Which store had the highest sales volume?',
     'sql_result': '   Store_Number  Total_Sales_Volume 0          2970             59322.0',
     'sql_generated': '```sql\nSELECT Store_Number, SUM(Total_Sale_Value) AS Total_Sales_Volume\nFROM sales\nGROUP BY Store_Number\nORDER BY Total_Sales_Volume DESC\nLIMIT 1;\n```'},
    {'question': 'Create a bar chart showing total sales by store',
     'sql_result': '    Store_Number    Total_Sales 0            880  420302.088397 1           1650  580443.007953 2           4180  272208.118542 3            550  229727.498752 4           1100  497509.528013 5           3300  619660.167018 6           3190  335035.018792 7           2970  836341.327191 8           3740  359729.808228 9           2530  324046.518720 10          4400   95745.620250 11          1210  508393.767785 12           330  370503.687331 13          2750  453664.808068 14          1980  242290.828499 15          1760  350747.617798 16          3410  410567.848126 17           990  378433.018639 18          4730  239711.708869 19          4070  322307.968330 20          3080  495458.238811 21          2090  309996.247965 22          1320  592832.067579 23          2640  308990.318559 24          1540  427777.427815 25          4840  389056.668316 26          2860  132320.519487 27          2420  406715.767402 28           770  292968.918642 29          3520  145701.079372 30           660  343594.978075 31          3630  405034.547846 32          2310  412579.388504 33          2200  361173.288199 34          1870  401070.997685',
     'sql_generated': '```sql\nSELECT Store_Number, SUM(Total_Sale_Value) AS Total_Sales\nFROM sales\nGROUP BY Store_Number;\n```'},
    {'question': 'What percentage of items were sold on promotion?',
     'sql_result': '   Promotion_Percentage 0              0.625596',
     'sql_generated': "```sql\nSELECT \n    (SUM(CASE WHEN On_Promo = 'Yes' THEN 1 ELSE 0 END) * 100.0) / COUNT(*) AS Promotion_Percentage\nFROM \n    sales;\n```"},
    {'question': 'What was the average transaction value?',
     'sql_result': '   Average_Transaction_Value 0                  19.018132',
     'sql_generated': '```sql\nSELECT AVG(Total_Sale_Value) AS Average_Transaction_Value\nFROM sales;\n```'},
    {'question': 'Create a line chart showing sales in 2021',
     'sql_result': '  sale_month  total_quantity_sold  total_sales_value 0 2021-11-01              43056.0      499984.428193 1 2021-12-01              75724.0      910982.118423',
     'sql_generated': '```sql\nSELECT MONTH(Sold_Date) AS Month, SUM(Total_Sale_Value) AS Total_Sales\nFROM sales\nWHERE YEAR(Sold_Date) = 2021\nGROUP BY MONTH(Sold_Date)\nORDER BY MONTH(Sold_Date);\n```'},
]


def run_agent_task(example) -> dict:
    print("Starting agent with messages:", example.input.get("question"))
    messages = [{"role": "user", "content": example.input.get("question")}]
    run_agent(messages)  # mutates `messages` in place; return value is just the final text
    return process_messages(messages)


def _run_overall(dataset, experiment_name: str, description: str):
    evaluators = _make_overall_evaluators()  # fresh evaluator objects per experiment
    experiment = run_experiment(dataset=dataset,
                                task=run_agent_task,
                                evaluators=evaluators,
                                experiment_name=experiment_name,
                                experiment_description=description,
                                timeout=120)
    print_experiment_summary(evals_to_df(experiment), experiment_name)
    return experiment


def lab11(skip_prompt_change: bool = False):
    """Full evaluator suite on the overall dataset, then the v2 rerun with a
    modified SQL-generation prompt (the prompt-comparison the lab teaches)."""
    update_sql_gen_prompt(DEFAULT_SQL_PROMPT)  # fresh state each lab run

    dataset = get_or_create_dataset("overall_experiment",
                                    pd.DataFrame(OVERALL_QUESTIONS),
                                    output_keys=["sql_result", "sql_generated"])

    print(f"\nPhoenix UI: {get_phoenix_endpoint()}")
    experiment = _run_overall(dataset, "Overall Experiment",
                              "Evaluating the overall experiment")

    if skip_prompt_change:
        return experiment

    # --- v2: same suite with the modified SQL prompt ---
    update_sql_gen_prompt(NEW_SQL_PROMPT)
    print("\nSQL prompt updated. Playground prompt (paste into Phoenix UI if desired):")
    print(get_sql_gen_prompt())

    experiment = _run_overall(dataset, "Overall Experiment v2",
                              "Evaluating the overall experiment, with changes to sql prompt")

    update_sql_gen_prompt(DEFAULT_SQL_PROMPT)  # restore for any later lab runs
    print(f"\nPhoenix UI: {get_phoenix_endpoint()}  (project: {PROJECT_NAME})")
    print("Experiments view (dataset page) shows 'Overall Experiment' and "
          "'Overall Experiment v2' runs with scores.")
    return experiment


# ======================================================================
# Dispatch
# ======================================================================

LABS = {"3": lab3, "5": lab5, "7": lab7, "9": lab9, "11": lab11}


def main():
    choice = sys.argv[1] if len(sys.argv) > 1 else "11"
    if choice == "all":
        # eval.py 3 must run interactively — "all" skips it (non-interactive).
        for key in ("5", "7", "9", "11"):
            print(f"\n{'#' * 20}  LAB {key}  {'#' * 20}")
            LABS[key]()
    elif choice in LABS:
        LABS[choice]()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()