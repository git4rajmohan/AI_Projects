"""Local evaluation launcher: python -m streamlit run app.py."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
EVAL_SCRIPT = ROOT / "eval.py"
PROJECT_NAME = "evaluating-agent"
LABS = {
    "Lab 5 - Tracing demo": "5",
    "Lab 7 - Router and skill evaluations": "7",
    "Lab 9 - Convergence evaluation": "9",
    "Lab 11 - Overall evaluation": "11",
    "Run all non-interactive labs": "all",
}
LAB_GUIDE = {
    "5": ("Trace 2 sales questions", "2 answers + Phoenix traces",
          "No quality score; verify answers against the source data."),
    "7": ("Check routing, SQL, clarity and chart code", "Score 1.00 for every check",
          "Scores cover all matching stored project spans, not just this run."),
    "9": ("Compare agent paths for 17 question variations", "Convergence 1.00 = shortest observed path",
          "Efficiency only; a short path does not prove a correct answer."),
    "11": ("Test 7 questions with 5 evaluators, then change the SQL prompt",
           "Score 1.00 for each evaluator in both runs",
           "Compare original vs. v2; investigate regressions before adopting the prompt."),
    "all": ("Run Labs 5 → 7 → 9 → 11", "Demo answers + all evaluation summaries",
            "Includes tracing, skills, efficiency and overall quality; excludes interactive Lab 3."),
}
EVALUATORS = {
    "Tool Calling Eval": ("Tool selection", "Inspect wrong tool choices and arguments."),
    "Runnable Code Eval": ("Chart code", "Inspect generated code and execution errors."),
    "Response Clarity": ("Answer clarity", "Inspect unclear answers and simplify the response prompt."),
    "SQL Gen Eval": ("SQL generation", "Check generated SQL against each question and schema."),
    "Convergence Eval": ("Path efficiency", "Inspect longer trajectories for redundant tool calls."),
    "function_calling_eval": ("Tool selection", "Inspect wrong tool choices and arguments."),
    "evaluate_sql_result": ("SQL results", "Compare actual results with references; check both SQL and reference data."),
    "evaluate_clarity": ("Answer clarity", "Inspect unclear answers and simplify the response prompt."),
    "evaluate_entity_correctness": ("Entity accuracy", "Check store IDs, SKUs and dates against the question and data."),
    "code_is_runnable": ("Chart code", "Inspect generated code and execution errors."),
}
CHECK_REFERENCE = {
    "Tool selection": (
        "Judges tool choice and, in Lab 7, arguments.",
        "Router in run_agent → handle_tool_calls.",
    ),
    "Chart code": (
        "Executes generated Python; does not verify chart accuracy.",
        "generate_visualization → extract_chart_config → create_chart.",
    ),
    "Answer clarity": (
        "Judges whether the response is clear and relevant, not factually correct.",
        "Lab 7: AGENT span output; Lab 11: final answer.",
    ),
    "SQL generation": (
        "Judges whether SQL addresses the question using the available schema.",
        "lookup_sales_data → generate_sql_query, before DuckDB execution.",
    ),
    "Path efficiency": (
        "Shortest observed message count ÷ this run's message count; not answer accuracy.",
        "Full run_agent trajectory across 17 question variations.",
    ),
    "SQL results": (
        "Compares concatenated digits with a reference, not full result semantics.",
        "lookup_sales_data output after DuckDB execution.",
    ),
    "Entity accuracy": (
        "Judges identifiers against the question; not independent database verification.",
        "Final answer: store numbers, SKUs, dates and other entities.",
    ),
}


@st.cache_data(ttl=300)
def fetch_trace_summary():
    """Query Phoenix for the latest AgentRun traces. Returns
    {question: {"tree": [...], "details": [rows]}}, span-kind counts, or error."""
    try:
        from phoenix.trace.dsl import SpanQuery
        from phoenix.client import Client

        endpoint = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006").rstrip("/") + "/"
        client = Client(base_url=endpoint)
        roots = client.spans.get_spans_dataframe(
            query=SpanQuery().where("name == 'AgentRun'").select(
                question="input.value", trace="context.trace_id", start="start_time"),
            project_name=PROJECT_NAME, timeout=30)
        if roots.empty:
            return {}, pd.DataFrame(), None
        roots["start"] = roots["start"].astype(str)
        roots = roots.sort_values("start")

        def question_of(value):
            match = re.search(r'"content":\s*"([^"]+)"', str(value))
            return match.group(1) if match else str(value)

        def clip(value, limit=900):
            text = re.sub(r"\s+", " ", str(value)).strip()
            return text[:limit] + ("…" if len(text) > limit else "")

        def payload_of(value):
            """JSON message arrays → 'role: content' lines; otherwise clipped text."""
            text = str(value)
            if text.startswith("["):
                try:
                    msgs = [m for m in json.loads(text) if isinstance(m, dict)]
                    rows = "\n".join(
                        f"{m.get('role', '?')}: {clip(m.get('content', ''), 500)}"
                        for m in msgs if "role" in m)
                    if rows:
                        return rows
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass
            return clip(text)

        traces = {}
        for _, root in roots.tail(4).iterrows():
            question = question_of(root["question"])
            spans = client.spans.get_spans_dataframe(
                query=SpanQuery().where("trace_id == '%s'" % root["trace"]).select(
                    name="name", kind="span_kind", start="start_time",
                    status="status_code", parent="parent_id",
                    inp="input.value", out="output.value"),
                project_name=PROJECT_NAME, timeout=30)
            if spans.empty:
                continue
            spans["start"] = spans["start"].astype(str)
            spans = spans.sort_values("start")
            children = {}
            for sid, row in spans.iterrows():
                children.setdefault(row["parent"], []).append(sid)
            lines, details = [], []
            def walk(sid, depth=0):
                row = spans.loc[sid]
                mark = "" if row["status"] == "OK" else "  ⚠️"
                lines.append("  " * depth + f"{row['name']} ({row['kind']}){mark}")
                if row["kind"] != "AGENT":
                    details.append({
                        "Span": f"{'· ' * depth}{row['name']}",
                        "Input": payload_of(row["inp"]),
                        "Output / result": payload_of(row["out"]),
                    })
                for child in children.get(sid, []):
                    walk(child, depth + 1)
            walk([sid for sid, row in spans.iterrows()
                  if row["parent"] is None or pd.isna(row["parent"])][0])
            traces[question] = {"tree": lines, "details": details}
        tally = spans["kind"].value_counts()  # ponytail: last trace only, fine for a demo
        counts = pd.DataFrame({"Span kind": list(tally.index),
                               "Count": [int(v) for v in tally.values]})
        return traces, counts, None
    except Exception as error:
        return {}, pd.DataFrame(), str(error)


JUDGE_KIND = {  # Lab 7 eval name → how it grades
    "Tool Calling Eval": "LLM judge",
    "Runnable Code Eval": "code-based",
    "Response Clarity": "LLM judge",
    "SQL Gen Eval": "LLM judge",
    # Lab 9/11 evaluator names
    "Convergence Eval": "code-based",
    "function_calling_eval": "LLM judge",
    "evaluate_sql_result": "code-based",
    "evaluate_clarity": "LLM judge",
    "evaluate_entity_correctness": "LLM judge",
    "code_is_runnable": "code-based",
}
EXPECTED_BY_EVAL = {  # what each judge is told counts as success
    "Tool Calling Eval": "correct tool + parameters for the question",
    "Runnable Code Eval": "generated chart code executes without error (exec, no LLM)",
    "Response Clarity": "label: clear",
    "SQL Gen Eval": "label: correct",
}


@st.cache_data(ttl=600)
def fetch_eval_examples():
    """Lab 7 graded examples: span annotations (judge label/score/explanation)
    plus the span's own input/output (question, tool calls, SQL, code).
    Returns {eval_name: [{"Label","Score","Judge reasoning",...}]} or error str."""
    import urllib.request

    def gql(query):
        req = urllib.request.Request(
            os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006").rstrip("/") + "/graphql",
            data=json.dumps({"query": query}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        if body.get("errors"):
            raise RuntimeError(body["errors"][0].get("message", "graphql error"))
        return body["data"]

    def first_user_content(value):
        try:
            for m in json.loads(value):
                if isinstance(m, dict) and m.get("role") == "user":
                    return m.get("content", "")
        except (json.JSONDecodeError, TypeError):
            pass
        return ""

    def assistant_message(value):
        try:
            return json.loads(value)["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return {}

    data = gql("""{ projects(first: 5) { edges { node { name
      spans(first: 200, sort: {col: startTime, dir: desc}) { edges { node {
        name spanKind
        input { value } output { value }
        spanAnnotations { name label score explanation }
    } } } } } } }""")
    project = next((p["node"] for p in data["projects"]["edges"]
                    if p["node"]["name"] == PROJECT_NAME), None)
    examples = {}
    if not project:
        return {}
    for edge in project["spans"]["edges"]:
        node = edge["node"]
        for ann in node["spanAnnotations"]:
            name = ann["name"]
            row = {"Label": ann["label"], "Score": ann["score"],
                   "Judge reasoning": ann["explanation"]}
            out = assistant_message((node.get("output") or {}).get("value", ""))
            if name == "Tool Calling Eval":
                row["Question"] = first_user_content((node.get("input") or {}).get("value", ""))
                row["Tool calls"] = json.dumps(out.get("tool_calls", []), indent=2)[:900]
            elif name == "SQL Gen Eval":
                row["Question"] = first_user_content((node.get("input") or {}).get("value", ""))
                row["Question"] = re.sub(r"(?s).*The prompt is: (.*?)\n+The available.*", r"\1",
                                         row["Question"]) if "The prompt is:" in row["Question"] else row["Question"]
                row["SQL"] = out.get("content", "")
            elif name == "Response Clarity":
                row["Question"] = first_user_content((node.get("input") or {}).get("value", ""))
                row["Answer"] = str((node.get("output") or {}).get("value", ""))[:900]
            elif name == "Runnable Code Eval":
                row["Generated code"] = str((node.get("output") or {}).get("value", ""))[:900]
            examples.setdefault(name, []).append(row)
    for rows in examples.values():
        rows.sort(key=lambda r: str(r.get("Judge reasoning")))
    return examples


def render_eval_details(run_choice):
    """Per-evaluator 'How this was tested': judge type, expectation, examples."""
    st.subheader("How this was tested")
    if LABS[run_choice] == "7":
        examples = fetch_eval_examples()
        if not isinstance(examples, dict):
            st.warning(f"Could not read annotations from Phoenix: {examples}")
            return
        for name in ("Tool Calling Eval", "Runnable Code Eval",
                     "Response Clarity", "SQL Gen Eval"):
            rows = examples.get(name, [])
            with st.container(border=True):
                st.markdown(f"#### {name} · `{JUDGE_KIND[name]}`")
                st.caption(f"Expected: {EXPECTED_BY_EVAL[name]}")
                if not rows:
                    st.caption("No graded examples found in Phoenix for this check.")
                    continue
                passes = sum(1 for r in rows if r["Score"] == 1.0)
                st.caption(f"{passes}/{len(rows)} graded pass · " +
                           ("LLM judge reads the recorded span and replies JSON label+reasoning."
                            if JUDGE_KIND[name] == "LLM judge"
                            else "Code runs the recorded artifact directly; no LLM involved."))
                for row in rows:
                    with st.container(border=True):
                        mark = "🟢" if row["Score"] == 1.0 else "🔴"
                        st.markdown(f"**{mark} {row['Label']}** — score {row['Score']}")
                        st.markdown(f"**Judge reasoning:** {row['Judge reasoning']}")
                        for key in ("Question", "Tool calls", "Answer", "SQL", "Generated code"):
                            if row.get(key):
                                st.markdown(f"**{key}:**")
                                st.code(str(row[key]),
                                        language="sql" if key == "SQL" else "text")
    else:
        st.caption(" · ".join(
            f"{name}: `{JUDGE_KIND[name]}`" for name in
            ([("Convergence Eval")] if LABS[run_choice] == "9"
             else ["function_calling_eval", "evaluate_sql_result", "evaluate_clarity",
                   "evaluate_entity_correctness", "code_is_runnable"])))
        st.caption("Per-example inputs and explanations: Phoenix → Experiments view "
                   "(dataset page) → open the experiment run.")


def parse_output(text):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    answers = re.findall(
        r"(?ms)^Q: ([^\n]+)\nA: (.*?)(?=^(?:Starting main span|Phoenix UI:|={4,})|\Z)",
        text,
    )
    summaries = [
        json.loads(line.removeprefix("__EVAL_UI__"))
        for line in text.splitlines() if line.startswith("__EVAL_UI__")
    ]
    return answers, summaries, text


load_dotenv(ROOT / ".env")
st.set_page_config(page_title="Agent Evaluation", layout="wide")
st.title("Agent Evaluation")
st.caption("Run evaluations here; explore traces and experiments in Phoenix.")

choice = st.selectbox("Evaluation", LABS)
action, expected, note = LAB_GUIDE[LABS[choice]]
with st.container(border=True):
    left, right = st.columns(2)
    left.markdown(f"**What it does**  \n{action}")
    right.markdown(f"**Expected output / target**  \n{expected}")
    st.caption(note)
with st.expander("Reference: checks and agent flow", expanded=False):
    st.markdown("**Question → router → sales lookup / SQL → optional analysis or chart code → final answer**")
    st.caption("Evaluators observe the agent; they are not extra steps in its execution.")
    st.dataframe(
        [{"Check": name, "What it checks": details[0], "Where used in agent": details[1]}
         for name, details in CHECK_REFERENCE.items()],
        hide_index=True, width="stretch",
    )
    st.caption(
        "Lab 7 includes matching historical Phoenix spans. Lab 11 treats missing SQL/chart "
        "tool responses as passing those checks, so inspect tool selection too."
    )
st.link_button("Open Phoenix results", os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006"))
st.caption("Runs use your configured model API and may take several minutes.")

if st.button("Run evaluation", type="primary"):
    output = []
    st.session_state.pop("run", None)
    status = st.status(f"Running {choice}...", expanded=False)
    try:
        with subprocess.Popen(
            [sys.executable, "-u", str(EVAL_SCRIPT), LABS[choice]],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as process:
            for line in process.stdout:
                output.append(line)
                status.code(line.rstrip())
            return_code = process.wait()
    except OSError as error:
        status.update(label="Could not start run", state="error")
        st.error(str(error))
    else:
        status.update(label="Run finished", state="complete" if return_code == 0 else "error")
        st.session_state.run = (choice, "".join(output), return_code)

if "run" not in st.session_state or st.session_state.run[0] != choice:
    st.info("No current output for this selection. Click Run evaluation.")
elif "run" in st.session_state:
    run_choice, output, return_code = st.session_state.run
    answers, summaries, log = parse_output(output)
    st.subheader(run_choice)
    if return_code == 0:
        st.success("Run completed. This means execution finished, not that every evaluation passed.")
    else:
        st.error(f"Run failed with exit code {return_code}. See technical logs below.")

    if answers:
        st.subheader("Results")
        for question, answer in answers:
            with st.container(border=True):
                st.info(question)
                st.markdown(answer.strip())

    if LABS[run_choice] == "5":
        st.metric("Answers returned / expected", f"{len(answers)} / 2")
        st.info("Result: answers generated, not correctness-verified. Next: verify key figures against the data and inspect Phoenix traces.")
    elif summaries:
        st.subheader("Evaluation scores")
        st.caption("Target: 1.00. Full score = all reported checks scored 1, not proof of correctness. Convergence measures efficiency only.")
        for summary in summaries:
            st.markdown(f"#### {summary['title']}")
            rows = []
            for row in summary["scores"]:
                check = EVALUATORS.get(row["evaluator"], (row["evaluator"], ""))[0]
                description, location = CHECK_REFERENCE.get(
                    check, ("Unknown evaluator; inspect Phoenix details.", "See Phoenix trace."),
                )
                score = row["score"]
                label = "No score" if score is None else (
                    "Pass" if row["passed"] == row["total"] else "Fail" if score == 0 else "Partial"
                )
                rows.append({
                    "Check": check,
                    "What it checks": description,
                    "Where used in agent": location,
                    "Expected": "1.00",
                    "Passed / total": f"{row['passed']} / {row['total']}",
                    "Current": score,
                    "Status": {"Pass": "🟢 Pass", "Partial": "🟠 Partial",
                               "Fail": "🔴 Fail", "No score": "⚪ No score"}[label],
                    "Next action": ("Inspect logs; no usable score." if score is None else
                                    "Target met; spot-check in Phoenix." if label == "Pass" else
                                    EVALUATORS.get(row["evaluator"], ("", "Inspect failed examples in Phoenix."))[1]),
                })
            st.dataframe(
                rows, hide_index=True, width="stretch",
                column_config={
                    "Check": st.column_config.TextColumn(help="The agent behavior evaluated."),
                    "What it checks": st.column_config.TextColumn(help="Check definition and its limitations."),
                    "Where used in agent": st.column_config.TextColumn(help="Agent stage or function observed by this evaluator."),
                    "Expected": st.column_config.TextColumn(help="Target score; currently 1.00."),
                    "Passed / total": st.column_config.TextColumn(help="Checks scoring exactly 1 out of all reported checks."),
                    "Current": st.column_config.ProgressColumn(
                        "Current", min_value=0, max_value=1, format="%.2f",
                        help="Average score from 0 to 1; convergence measures efficiency.",
                    ),
                    "Status": st.column_config.TextColumn(help="Pass: all scored 1. Partial: nonzero average below full success. Fail: average 0. No score: unavailable."),
                    "Next action": st.column_config.TextColumn(help="Suggested follow-up based on the result."),
                },
            )
    else:
        st.warning(f"No evaluation scores were reported. Check technical logs and Phoenix.")

    st.subheader("Traces")
    lab = LABS[run_choice]
    if lab == "5":
        st.caption(
            "Agent traces for the 2 demo questions, queried from Phoenix after the run. "
            "Full detail (prompts, SQL, timing) lives in the Phoenix UI."
        )
        traces, counts, error = fetch_trace_summary()
        if error or not traces:
            st.warning("Could not read traces from Phoenix. Check that it is running, then use the traces link above." if error
                       else "No AgentRun traces found yet; Phoenix may still be indexing. Rerun in a moment.")
        else:
            left, right = st.columns(2)
            left.dataframe(counts, hide_index=True)
            right.caption(f"{len(traces)} traced AgentRun(s) captured (last run shown).")
            for question, trace in traces.items():
                with st.container(border=True):
                    st.info(question)
                    st.code("\n".join(trace["tree"]), language="text")
                    with st.expander("Span inputs / outputs", expanded=False):
                        st.text_area(
                            "Span inputs / outputs", value="\n".join(
                                f"{row['Span']}\n  IN : {row['Input']}\n  OUT: {row['Output / result']}"
                                for row in trace["details"]),
                            height=420, disabled=True)
    elif lab in ("7", "9", "11"):
        render_eval_details(run_choice)
    else:
        st.caption("Open Phoenix to explore traces for this run.")

    with st.expander("Technical logs", expanded=False):
        st.code(log, language="text")
        st.download_button("Download logs", log, file_name="evaluation.log", mime="text/plain")
