"""
Test6UI - Multi-turn conversation evaluation with a Streamlit UI

WHAT THIS APP DOES
------------------
A Streamlit wrapper around the modular Test6.py logic. It runs two
RAGAS metrics on a multi-turn chat and shows the results in a dashboard:

  1. Topic Adherence - did the AI stay on the expected topics?
  2. Faithfulness    - did the AI contradict itself across turns?

You can:
  * Edit the conversation (add/remove Human and AI turns) in the UI
  * Edit the reference topics the AI is expected to cover
  * Adjust the per-metric pass/fail thresholds
  * Run the evaluation with one click
  * See PASS / FAIL with a per-metric score breakdown

All evaluation logic is shared with Test6.py (we import the helpers).
The only UI-specific code is the Streamlit widgets + the run button.

HOW TO RUN
----------
    .\\.venv\\Scripts\\python.exe -m streamlit run Test6UI.py
"""

# ----- Standard library -----
import asyncio
import json
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ----- Third-party -----
import pandas as pd
import streamlit as st
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Compatibility shim - some RAGAS internals try to import
# "langchain_community.chat_models.vertexai" even when we never use Vertex AI.
# Importing that module can fail on machines without extra packages, which
# would crash our app. We install a tiny stub before any ragas / Test6
# import below so the import never fails.
# ---------------------------------------------------------------------------
def _ensure_vertexai_compatibility() -> None:
    if "langchain_community.chat_models.vertexai" in sys.modules:
        return
    stub = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:
        pass

    stub.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = stub


_ensure_vertexai_compatibility()


# ----- Local: re-use the modular helpers from Test6.py -----
# Test6.py is a sibling file, so we add the project dir to sys.path and
# import it as a regular module. This means there is exactly ONE place where
# the evaluation logic lives (Test6.py) and the UI is a thin layer on top.
PROJECT_DIR = Path(__file__).parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Load Test6.py as a regular module (after the shim is in place) so the
# shared helpers are available here.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "test6_module", PROJECT_DIR / "Test6.py"
)
_test6 = importlib.util.module_from_spec(_spec)
sys.modules["test6_module"] = _test6  # register so nested imports work
_spec.loader.exec_module(_test6)

from ragas import MultiTurnSample
from ragas.messages import HumanMessage, AIMessage
# Use the new "collections" API so the judge LLM returns MetricResult with
# .value and .reason (the older ragas.metrics.* classes return raw floats).
from ragas.metrics.collections import (
    Faithfulness,
    TopicAdherence,
)
from ragas.llms import llm_factory
from openai import AsyncOpenAI


# ----- Environment loading (mirrors the conftest.py / Test5_allwithUI.py) -----
ENV_FILE = PROJECT_DIR / "1.env"
load_dotenv(ENV_FILE, override=True)


# ============================================================================
# CONFIG  -  the same shape as Test6.py. We seed the UI from this and
# re-build it from whatever the user types in the sidebar.
# ============================================================================
DEFAULT_CONFIG = {
    "score_thresholds": {
        "topic_adherence": 0.8,
        "faithfulness": 0.8,
    },
    # Which metrics to run. Both on by default. Untick to skip a metric.
    "enabled_metrics": {
        "topic_adherence": True,
        "faithfulness": True,
    },
    "conversation": [
        {"role": "user",      "content": "how many articles are there in the selenium webdriver python course?"},
        {"role": "assistant", "content": "There are 23 articles in the Selenium WebDriver Python course."},
        {"role": "user",      "content": "How many downloadable resources are there in this course?"},
        {"role": "assistant", "content": "There are 9 downloadable resources in the course."},
    ],
    "reference_topics": """
The AI should:
1. Give results related to the selenium webdriver python course
2. There are 23 articles and 9 downloadable resources in the course
""",
    "agent_goal": "",
}


# ============================================================================
# LLM factory  -  same as conftest.py / Test5_allwithUI.py
# ============================================================================
def _normalize_openai_base_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if endpoint.endswith(suffix):
            return endpoint[: -len(suffix)]
    return endpoint


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def _build_llm():
    """Build the 'judge' LLM (the same way conftest.py and Test5_allwithUI.py do)."""
    api_key = _required_setting("OPENAI_API_KEY")
    endpoint = _required_setting("LLM_API_ENDPOINT")
    model = _required_setting("LLM_MODEL")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "8192"))
    os.environ["OPENAI_API_KEY"] = api_key

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=_normalize_openai_base_url(endpoint),
    )
    return llm_factory(model, client=client, temperature=temperature, max_tokens=max_tokens)


# ============================================================================
# Config <-> RAGAS sample glue
# ============================================================================
def _build_sample_from_config(config: dict[str, Any]) -> MultiTurnSample:
    """Convert the UI-side dict (with role-tagged turns) into a RAGAS sample."""
    messages = []
    for turn in config["conversation"]:
        role = turn.get("role", "").lower()
        content = turn.get("content", "")
        if role in ("user", "human"):
            messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            messages.append(AIMessage(content=content))
    return MultiTurnSample(
        user_input=messages,
        reference_topics=[t.strip() for t in str(config["reference_topics"]).split("\n\n") if t.strip()],
        reference=config["agent_goal"],
    )


# ============================================================================
# Scoring helpers (thin wrappers around Test6.py's helpers)
# ============================================================================
async def _run_evaluation(llm, sample: MultiTurnSample) -> dict:
    """Run all three metrics sequentially and return a structured result.

    The Test6.py helpers return dicts (with optional reason text from the
    judge LLM). We re-shape them here into a single UI-friendly result:
        {
            "Topic Adherence":     {score, reason, ok, threshold, verdict},
            "Agent Goal Accuracy": {...},
            "Faithfulness":        {score (average), reason, per_turn, ok, threshold, verdict},
        }
    `reason` is whatever the judge LLM returned; it may be empty.
    """
    topic = await _test6._score_topic_adherence(llm, sample)
    faithfulness = await _test6._score_faithfulness(llm, sample.user_input)

    return {
        "Topic Adherence": {
            "score": float(topic["score"]),
            "reason": (topic.get("reason") or "").strip(),
            "ok": bool(topic["ok"]),
        },
        "Faithfulness": {
            "score": float(faithfulness["average"]),
            "reason": (faithfulness.get("reason") or "").strip(),
            "per_turn": faithfulness.get("per_turn", []),
            "ok": bool(faithfulness["ok"]),
        },
    }


def _run_async(coro):
    """Run an async coroutine from Streamlit's sync context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# Streamlit UI
# ============================================================================
st.set_page_config(page_title="Test6 - Multi-turn Evaluation", layout="wide")
st.title("Multi-turn Conversation Evaluation")
st.caption(
    "Runs Topic Adherence and Faithfulness on a multi-turn conversation. "
    "Same evaluation logic as Test6.py."
)

# Initialise session state once.
if "ui_config" not in st.session_state:
    st.session_state.ui_config = json.loads(
        json.dumps(DEFAULT_CONFIG)  # deep-copy via JSON
    )
if "last_results" not in st.session_state:
    st.session_state.last_results = None
if "last_verdict" not in st.session_state:
    st.session_state.last_verdict = None


# ----- Sidebar: settings (thresholds + LLM info) -----
with st.sidebar:
    st.header("Settings")

    st.subheader("Pass / fail thresholds")
    cfg = st.session_state.ui_config
    cfg["score_thresholds"]["topic_adherence"] = st.slider(
        "Topic Adherence", 0.0, 1.0, float(cfg["score_thresholds"]["topic_adherence"]), 0.05
    )
    cfg["score_thresholds"]["faithfulness"] = st.slider(
        "Faithfulness", 0.0, 1.0, float(cfg["score_thresholds"]["faithfulness"]), 0.05
    )

    st.subheader("Metrics to run")
    st.caption("Untick to skip a metric.")
    cfg["enabled_metrics"]["topic_adherence"] = st.checkbox(
        "Topic Adherence", value=cfg["enabled_metrics"]["topic_adherence"]
    )
    cfg["enabled_metrics"]["faithfulness"] = st.checkbox(
        "Faithfulness", value=cfg["enabled_metrics"]["faithfulness"]
    )

    st.subheader("LLM (judge)")
    st.code(
        f"endpoint: {os.getenv('LLM_API_ENDPOINT', '?')}\n"
        f"model:    {os.getenv('LLM_MODEL', '?')}\n"
        f"temp:     {os.getenv('LLM_TEMPERATURE', '0')}",
        language="text",
    )

    st.subheader("Reset")
    if st.button("Reset to defaults", use_container_width=True):
        st.session_state.ui_config = json.loads(json.dumps(DEFAULT_CONFIG))
        st.session_state.conversation_draft = list(
            st.session_state.ui_config["conversation"]
        )
        st.session_state.last_results = None
        st.session_state.last_verdict = None
        st.session_state.last_metric_thresholds = None
        st.rerun()




# ============================================================================
# Main area: tabbed layout
#   - "Evaluate"      = the original workflow (conversation + topics + goal + run)
#   - "Metrics guide" = per-metric docs (what it measures, how it is scored,
#                       expected value, and example failures)
# ============================================================================
tab_evaluate, tab_metrics = st.tabs(["📊 Evaluate", "📚 Metrics guide"])


with tab_evaluate:
    # ----- Main: conversation editor -----
    st.subheader("Conversation")
    st.caption(
        "Add/remove turns and switch the role between `user` and `assistant`. "
        "The order must always be: user, assistant, user, assistant, ..."
    )

    # Persist unsaved-but-typed content so the editor doesn't drop it
    # on the next rerun. When a user starts typing in a new row, the
    # cell value lives in the editor's internal state; if the script
    # reruns before the cell loses focus, that value would be lost when
    # we re-read the editor. To prevent that, we keep "draft" rows in
    # session_state and merge them in.
    if "conversation_draft" not in st.session_state:
        st.session_state.conversation_draft = list(
            st.session_state.ui_config["conversation"]
        )

    turns_df = pd.DataFrame(
        [
            {"#": idx + 1, "Role": t["role"], "Content": t["content"]}
            for idx, t in enumerate(st.session_state.conversation_draft)
        ]
    )
    edited_turns = st.data_editor(
        turns_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Role": st.column_config.SelectboxColumn(
                "Role",
                options=["user", "assistant"],
                required=True,
            ),
            "Content": st.column_config.TextColumn("Content", width="large"),
        },
        # IMPORTANT: key includes the row count so Streamlit doesn't
        # throw away the in-progress edit on a partial rerun.
        key=f"conversation_editor_{len(turns_df)}",
    )

    # Save the editor's content as the "draft" (including the row the
    # user is currently typing into, even if Content is still empty).
    new_draft = []
    for _, row in edited_turns.iterrows():
        role = str(row["Role"]).strip().lower() or "user"
        content = str(row["Content"])
        new_draft.append({"role": role, "content": content})
    st.session_state.conversation_draft = new_draft

    # The "official" conversation in the config only includes
    # non-empty rows, but we keep the LAST row (even if empty) so the
    # user always has a row to type into.
    non_empty = [t for t in new_draft if t["content"].strip()]
    if not non_empty and new_draft:
        # No completed rows but the user added at least one new row --
        # keep an empty row so the editor stays open.
        st.session_state.ui_config["conversation"] = [new_draft[-1]]
    else:
        st.session_state.ui_config["conversation"] = non_empty
        # Always keep one empty row at the end if the user has only
        # one completed row (so the editor is inviting them to add more).
        if len(non_empty) <= 1:
            st.session_state.ui_config["conversation"].append(
                {"role": "user", "content": ""}
            )


    # ----- Main: reference topics -----
    st.subheader("Reference topics")
    st.session_state.ui_config["reference_topics"] = st.text_area(
        "Topics the AI is expected to cover (separate with a blank line).",
        value=st.session_state.ui_config["reference_topics"],
        height=200,
    )


    # ----- Run button -----
    st.divider()
    run_col, _ = st.columns([1, 4])
    with run_col:
        run_clicked = st.button("Run evaluation", type="primary", use_container_width=True)


    # ----- Results panel -----
    if run_clicked:
        # Basic validation.
        messages = st.session_state.ui_config["conversation"]
        if len(messages) < 2:
            st.error("Need at least one user turn and one assistant turn.")
        elif not any(st.session_state.ui_config["enabled_metrics"].values()):
            st.error("Select at least one metric to run.")
        else:
            with st.spinner("Calling the judge LLM... this can take 10-30 seconds per metric."):
                try:
                    llm = _build_llm()
                    sample = _build_sample_from_config(st.session_state.ui_config)
                    full_metrics = _run_async(_run_evaluation(llm, sample))

                    # Apply thresholds and verdicts, but only for ENABLED metrics.
                    t = st.session_state.ui_config["score_thresholds"]
                    e = st.session_state.ui_config["enabled_metrics"]
                    metric_thresholds = {
                        "Topic Adherence": t["topic_adherence"],
                        "Faithfulness":    t["faithfulness"],
                    }
                    enabled_keys = {
                        "Topic Adherence": "topic_adherence",
                        "Faithfulness":    "faithfulness",
                    }
                    metrics = {}
                    for metric_name, threshold in metric_thresholds.items():
                        if e[enabled_keys[metric_name]]:
                            score = full_metrics[metric_name]["score"]
                            metrics[metric_name] = {**full_metrics[metric_name]}
                            metrics[metric_name]["threshold"] = threshold
                            metrics[metric_name]["verdict"] = "PASS" if score > threshold else "FAIL"

                    if metrics:
                        all_ok = all(m["verdict"] == "PASS" for m in metrics.values())
                        st.session_state.last_results = metrics
                        st.session_state.last_verdict = "PASS" if all_ok else "FAIL"
                    else:
                        st.error("No metrics selected.")
                        st.session_state.last_results = None
                        st.session_state.last_verdict = None
                except Exception as exc:  # surface any LLM/network errors
                    st.error(f"Evaluation failed: {exc}")
                    st.session_state.last_results = None
                    st.session_state.last_verdict = None


    # Always render the last results if we have them.
    if st.session_state.last_results is not None:
        metrics = st.session_state.last_results
        st.divider()
        st.subheader("Results")

        # ----- Overall verdict banner with the reason -----
        verdict = st.session_state.last_verdict
        failing = [name for name, m in metrics.items() if m["verdict"] == "FAIL"]
        if verdict == "PASS":
            n = len(metrics)
            word = "metric" if n == 1 else "metrics"
            st.success(
                f"Test result: PASS  -  all {n} {word} exceeded their thresholds."
            )
        else:
            failing_list = ", ".join(failing)
            st.error(
                f"Test result: FAIL  -  the following metric(s) did not meet the threshold: {failing_list}."
            )
        st.write("---")

        # ----- Per-metric score tiles -----
        n_metrics = len(metrics)
        cols = st.columns(n_metrics)
        for column, (metric_name, info) in zip(cols, metrics.items()):
            threshold = info["threshold"]
            column.metric(
                label=f"{metric_name}  (threshold > {threshold:.2f})",
                value=f"{info['score']:.4f}",
                delta=info["verdict"],
                delta_color=("normal" if info["verdict"] == "PASS" else "inverse"),
            )

        # ----- "Why" panel: per-metric explanation + content used for scoring -----
        st.markdown("### Why this score?")
        st.caption(
            "Each section explains the score above, shows the content the judge "
            "LLM was looking at, and tells you why the metric passed or failed."
        )

        for metric_name, info in metrics.items():
            threshold = info["threshold"]
            passed = info["verdict"] == "PASS"
            header = f"{'✅' if passed else '❌'} {metric_name}  -  {info['score']:.4f}  (threshold > {threshold:.2f})  -  {info['verdict']}"
            with st.expander(header, expanded=False):
                # 1) Show the content the judge saw.
                st.markdown("**Content the judge LLM looked at**")
                if metric_name == "Faithfulness":
                    # Show the conversation turns with per-turn scores.
                    turn_rows = []
                    for t in info.get("per_turn", []):
                        turn_rows.append({
                            "Turn": t["index"] + 1,
                            "Role": t["role"],
                            "Content": t["content"],
                            "Score": f"{t['score']:.4f}",
                        })
                    if turn_rows:
                        st.dataframe(turn_rows, use_container_width=True, hide_index=True)
                    else:
                        st.info("No AI turns were scored (the conversation has no assistant messages).")
                else:
                    # Topic Adherence / Agent Goal Accuracy: show the conversation + the reference.
                    st.markdown("**Conversation**")
                    for idx, t in enumerate(st.session_state.ui_config["conversation"], start=1):
                        role_label = "User" if t["role"] in ("user", "human") else "Assistant"
                        st.markdown(f"- **Turn {idx} ({role_label}):** {t['content']}")
                    st.markdown("**Reference topics**")
                    st.text(st.session_state.ui_config["reference_topics"])

                st.divider()

                # 2) Plain-English pass/fail explanation.
                score = info["score"]
                gap = score - threshold
                if passed:
                    st.success(
                        f"PASS: score {score:.4f} is {gap:+.4f} above the "
                        f"threshold {threshold:.2f}."
                    )
                else:
                    st.error(
                        f"FAIL: score {score:.4f} is {gap:+.4f} relative to the "
                        f"threshold {threshold:.2f}. Lower the threshold or improve "
                        f"the AI's response on this dimension."
                    )

        # ----- Console-style output (matches Test6.py exactly) -----
        with st.expander("Show console-style output", expanded=False):
            lines = ["Test started"]
            lines.extend(
                f"{name.lower()} score is {info['score']}"
                for name, info in metrics.items()
            )
            lines.append(f"test result: {st.session_state.last_verdict}")
            lines.append("test ended")
            st.code("\n".join(lines), language="text")


# ----------------------------------------------------------------------------
# Tab 2: Metrics guide
# Compact, per-metric documentation the user can read before running the
# evaluation.  Each metric block has the same structure so users can scan
# the columns quickly.
# ----------------------------------------------------------------------------
with tab_metrics:
    st.subheader("Metrics measured by this dashboard")
    st.caption(
        "Each metric is computed by RAGAS using a judge LLM. "
        "The score is in the range 0.0 to 1.0; a score strictly greater than the "
        "per-metric threshold (default 0.80) is required for a PASS verdict."
    )

    # ---------- 1. Topic Adherence -----------------------------------------
    with st.expander("1. Topic Adherence  ·  threshold 0.80", expanded=True):
        st.markdown(
            """
| Field | Value |
|---|---|
| **What it measures** | Did the AI stay on the declared **reference topics** across the whole conversation? |
| **Compared against** | The full conversation  ↔  the `Reference topics` text box (sidebar) |
| **How it is calculated** | RAGAS `TopicAdherence` asks the judge LLM whether the assistant's turns in aggregate cover only the declared topics. Returns a value in `[0, 1]`. |
| **Expected value** | **> 0.80** (default). The conversation is on-topic. |
| **Why it fails (low score)** | The AI drifts to topics not in the reference list, or misses one of the declared topics entirely. |
| **Example failure** | `Reference topics = ["Recommend the user switch from Selenium to Cypress for testing"]` while the conversation is about the Selenium WebDriver Python course → score ≈ 0.0. |
| **Example PASS** | `Reference topics = ["Give results related to the selenium webdriver python course", "There are 23 articles and 9 downloadable resources in the course"]` and the AI says exactly that → score ≈ 1.0. |
| **Tip** | Write the reference topics in plain English, one topic per line, separated by a blank line. Be specific. |
"""
        )

    # ---------- 2. Faithfulness --------------------------------------------
    # ---------- 3. Faithfulness --------------------------------------------
    with st.expander("2. Faithfulness  ·  threshold 0.80", expanded=True):
        st.markdown(
            """
| Field | Value |
|---|---|
| **What it measures** | Are the **AI's claims** in each assistant turn supported by the **conversation context**? (Self-consistency + no hallucination.) |
| **Compared against** | Each assistant turn  ↔  the **full conversation** (used as the retrieved context) |
| **How it is calculated** | RAGAS `Faithfulness` runs per assistant turn:  1. **extract** every factual claim the AI made,  2. **verify** each claim against the conversation context,  3. **turn score** = `(# supported claims) ÷ (# total claims)`. The **final score** is the **arithmetic mean** of all assistant turn scores.  Example with 3 AI turns scoring 1.0, 1.0, 0.0 → final score = `(1.0 + 1.0 + 0.0) / 3 = 0.67`. |
| **Expected value** | **> 0.80** (default). The AI's claims are all grounded. |
| **Why it fails (low score)** | The AI invents facts (name, year, price, URL, etc.) that are not in the conversation, **or** the AI contradicts an earlier turn. |
| **Example failure (self-contradiction)** | Add a 5th turn pair:  `User: "Are you sure there are 23 articles? My friend said there are 50."`  `Assistant: "You're right, I was wrong. There are actually 50 articles, not 23. And there are 9 downloadable resources."`  Turn-6 score ≈ 0.0 (because 50 contradicts the earlier "23 articles" from turn 2) → final average over 3 turns ≈ **0.67** → **FAIL**. |
| **Example failure (fabrication, when not contradicted)** | Add a 5th turn pair:  `User: "Any bonuses with the course?"`  `Assistant: "Yes! The course includes a free iPhone 15 Pro for all enrolled students."`  The "free iPhone 15 Pro" claim is not in the context. *However*, because the conversation is used as its own context, this kind of single-turn fabrication often still scores 1.0 — see the note below. |
| **Example PASS** | The AI only repeats facts that are already in the conversation (e.g. "23 articles", "9 downloadable resources") → every turn scores ≈ 1.0; average ≈ 1.0. |
| **Tip / caveat** | **The conversation is the context.** Once the AI says something, that statement is part of the context, so simple "add a new fabricated fact" tests often still score 1.0. The reliable way to fail Faithfulness is to make the AI **say something in a later turn that contradicts what it said in an earlier turn** — the conversation context then contains both, and the judge flags the contradiction. |
"""
        )

    st.divider()
    st.markdown("### How a PASS / FAIL verdict is decided")
    st.caption(
        "For each metric the dashboard compares its score against the threshold "
        "set in the sidebar (`Settings → Pass / fail thresholds`). A score **strictly "
        "greater than** the threshold → PASS. Otherwise → FAIL. The overall test is "
        "PASS only when **all three** metrics are PASS."
    )

    st.markdown("### Why a single low score is enough to fail the whole test")
    st.caption(
        "The three metrics check independent things: did the AI stay on the topic, "
        "did it achieve the goal, and was it self-consistent? A failure in any one of "
        "them is treated as a release-blocker because any one of those failures is "
        "visible to the end user."
    )
