# # app.py — Execution wiring + result panels (spec sections 5/6/9–16/19/20; Phase 7).
import requests
import streamlit as st

from config.settings import (
    OLLAMA_CLOUD_HOST,
    OLLAMA_CLOUD_MODEL,
    OLLAMA_HOST,
    TEV1_MODEL,
    validate_settings,
)
from prompts import (
    MODE_TEMPLATES,
    autofill_criteria,
    build_combined_prompt,
    build_decision_request,
)
from prompts import custom as custom_mode
from prompts.general import (
    DEFAULT_CATEGORIES as GEN_DEFAULT_CATEGORIES,
    DEFAULT_INSTRUCTIONS as GEN_DEFAULT_INSTRUCTIONS,
)
from prompts.general import build_questions as gen_build_questions
from services.llm_service import LlmError, call_llm
from services.result_processor import (
    build_comparison,
    format_probabilities,
    summarize_llm,
    summarize_tev1,
)
from services.tev1_service import Tev1Error, call_tev1

DEMO_MODES = ("Customer Support", "QA / Testing", "General Decision", "Custom")
EXECUTION_MODES = ("LLM Only", "Tev1 + LLM", "Compare Both")
PLACEHOLDER = (
    "Enter a customer issue, bug report, requirement, "
    "document statement, or any scenario..."
)

# Spec section 17 examples only — presets fill the textbox; decisions are never
# hard-coded anywhere (plan 8.4).
MODE_PRESETS = {
    "Customer Support": (
        "Customer was charged twice for the same subscription."
    ),
    "QA / Testing": (
        "Login fails when Japanese characters are entered in the password field."
    ),
    "General Decision": (
        "This document section explains an important security requirement."
    ),
    "Custom": "",  # no spec section 17 example; user builds the config themselves
}


@st.cache_data(ttl=30)  # ponytail: cached preflight so widget reruns stay snappy
def _service_status() -> dict:
    """Cheap up/reachable probes — version GET on local Ollama, GET on the
    cloud host. Any HTTP response means the service answers; the API key is
    never used here and never displayed (spec sections 8/25)."""
    local = cloud = False
    try:
        local = requests.get(f"{OLLAMA_HOST}/api/version", timeout=2).ok
    except requests.exceptions.RequestException:
        pass
    try:
        cloud = requests.get(OLLAMA_CLOUD_HOST, timeout=3).ok
    except requests.exceptions.RequestException:
        pass
    return {"local": local, "cloud": cloud}


st.set_page_config(page_title="Decision + LLM Playground", layout="wide")
st.title("Decision + LLM Playground")
st.subheader("Explore how structured decision models can complement generative LLMs.")

# --- Sidebar: configuration facts only; the API key is never shown there.
with st.sidebar:
    st.header("Configuration")
    st.markdown("**Decision Model**")
    st.write(TEV1_MODEL)
    st.markdown("**Generative LLM**")
    st.write(OLLAMA_CLOUD_MODEL or "*(not configured — set OLLAMA_CLOUD_MODEL in .env)*")
    st.markdown("**Ollama Host**")
    st.write(OLLAMA_HOST)

    status = _service_status()
    st.caption(
        f"Local Ollama: {'🟢 up' if status['local'] else '🔴 down'} · "
        f"Ollama Cloud: {'🟢 reachable' if status['cloud'] else '🔴 unreachable'}"
    )

# --- Input section (spec section 7). Picking a mode presets the scenario
# textbox with that mode's example (plan 8.1): the selectbox on_change callback
# writes the preset into the scenario widget's key BEFORE the next rerun
# instantiates it. An empty preset (Custom: user builds the config themselves)
# never clobbers typed text.


def _preset_scenario() -> None:
    preset = MODE_PRESETS[st.session_state["demo_mode"]]
    if preset:
        st.session_state["scenario_text"] = preset


st.subheader("Input")
if "scenario_text" not in st.session_state:
    st.session_state["scenario_text"] = MODE_PRESETS["Customer Support"]
demo_mode = st.selectbox("Demo Mode", DEMO_MODES, key="demo_mode",
                         on_change=_preset_scenario)
scenario = st.text_area("Scenario", key="scenario_text", placeholder=PLACEHOLDER)

# Custom mode form (spec section 15) — validated BEFORE any API call (plan 8.2f).
custom_config = None
custom_error = None
if demo_mode == "Custom":
    with st.expander("Custom decision configuration", expanded=True):
        custom_question = st.text_input(
            "Decision Question", key="custom_question",
            placeholder="What is the priority of this issue?",
        )
        decision_type = st.selectbox("Decision Type", ("Choice", "Yes / No", "Score"),
                                     key="custom_type")
        if decision_type == "Choice":
            st.caption("Comma- or line-separated list of options (2-26).")
            custom_choices = st.text_area("Choices", key="custom_choices",
                                          placeholder="High, Medium, Low")
        else:
            custom_choices = ""
            if decision_type == "Score":
                st.caption("Score scale 1-10 (Tev1 returns a numeric score + legend): "
                           + custom_mode.SCORE_CHOICES_TEXT)
        custom_criteria = st.text_area(
            "Criteria (optional)", key="custom_criteria",
            placeholder=("Describe each choice - '<Choice>:' on its own line, "
                         "description below:\n\nHigh:\nMajor functionality is "
                         "unavailable.\n\nMedium:\nWorkaround exists but limited.\n\n"
                         "Low:\nMinor issue with limited impact.")
            if decision_type in ("Choice", "Yes / No") else
            ("One description per line, aligned with scores 1-10:\n\nminor\nmoderate\n"
             "major\n... (10 lines)")
        )
        try:
            custom_config = custom_mode.validate_config(
                custom_question, decision_type, custom_choices, custom_criteria)
        except custom_mode.CustomModeError as exc:
            custom_error = str(exc)

# General Decision mode: categories + instruction editable at runtime (plan 8.3,
# spec section 5 mode 3). Empty entries keep the built-in defaults.
if demo_mode == "General Decision":
    with st.expander("General Decision configuration (optional edits)"):
        st.text_area(
            "Categories (comma-separated)", key="gen_categories",
            value=", ".join(GEN_DEFAULT_CATEGORIES),
        )
        st.text_input("Classifier instruction", key="gen_instructions",
                      value=GEN_DEFAULT_INSTRUCTIONS)
        st.caption("Leave a field empty to keep its built-in default.")

execution_mode = st.radio("Execution Mode", EXECUTION_MODES, horizontal=True)
analyze = st.button("Analyze")

# --- Panel renderers (spec sections 9/10/11/16/20).
# Result card builders take the session-stored result dict; every number they
# show is a value the API actually returned (never an example value).


def _render_tev1_card(tev1: dict) -> None:
    st.markdown("#### Tev1 Decision")
    st.metric("Decision", tev1["decision"] or "not returned")
    confidence = tev1.get("confidence")
    if isinstance(confidence, (int, float)):
        st.metric("Confidence", f"{confidence * 100:.1f}%")
    else:
        st.metric("Confidence", "not returned")
    if tev1.get("probabilities"):
        st.markdown("**Probability**")
        for label, pct in tev1["probabilities"]:      # spec sec 9: bars for real probs
            st.progress(min(max(pct, 0.0), 1.0), text=f"{label}  {pct * 100:5.1f}%")
        st.caption(format_probabilities(tev1["probabilities"]))
    for name, (choice, _conf) in (tev1.get("extra_answers") or {}).items():
        st.metric(f"Secondary question: {name}", choice or "not returned")
    input_tokens = tev1.get("input_tokens")
    output_tokens = tev1.get("output_tokens")
    if input_tokens is not None or output_tokens is not None:
        cols = st.columns(2)
        cols[0].metric("Input tokens", input_tokens if input_tokens is not None else "n/a")
        cols[1].metric("Output tokens", output_tokens if output_tokens is not None else "n/a")
    if tev1.get("elapsed_s") is not None:
        st.caption(f"Tev1 response time: **{tev1['elapsed_s']} sec** (measured)")


def _render_llm_card(llm: dict) -> None:
    st.markdown("#### Ollama Cloud LLM")
    st.write(llm.get("text") or "*(no response text returned)*")
    st.caption(f"Model: **{llm.get('model')}** · processing time (Ollama Cloud LLM): **{llm.get('elapsed_s')} sec** (measured)")
    prompt_tokens = llm.get("prompt_tokens")
    eval_tokens = llm.get("eval_tokens")
    if prompt_tokens is not None or eval_tokens is not None:
        cols = st.columns(2)
        cols[0].metric("Input tokens", prompt_tokens if prompt_tokens is not None else "n/a")
        cols[1].metric("Output tokens", eval_tokens if eval_tokens is not None else "n/a")
    if llm.get("thinking"):
        with st.expander("LLM thinking trace"):
            st.text(llm["thinking"])


def _render_combined_card(tev1: dict, llm: dict) -> None:
    """Final AI Response (spec sec 11): three labeled sub-sections per role."""
    st.markdown("#### Final AI Response")
    with st.container(border=True):
        st.markdown("##### Decision (generated by Tev1)")
        _render_decision_block(tev1)
    with st.container(border=True):
        st.markdown("##### Explanation (generated by the LLM)")
        st.write(llm.get("text") or "*(no response text returned)*")
    st.caption("Recommended Action (generated by the LLM) — the combined prompt asks "
               "the LLM for it inside its labeled response above.")


def _render_decision_block(tev1: dict) -> None:
    st.markdown(f"**Decision:** {tev1.get('decision') or 'not returned'}")
    confidence = tev1.get("confidence")
    st.markdown(
        f"**Confidence:** {confidence * 100:.1f}%"
        if isinstance(confidence, (int, float)) else "**Confidence:** not returned"
    )
    if tev1.get("probabilities"):
        st.markdown("**Probability**")
        for label, pct in tev1["probabilities"]:
            st.progress(min(max(pct, 0.0), 1.0), text=f"{label}  {pct * 100:5.1f}%")


def _render_compare(tev1: dict, llm_only: dict, llm_combined: dict) -> None:
    """Compare Both (spec sec 16/20): real facts side by side; no LLM confidence."""
    combined = build_comparison(tev1, llm_combined)["tev1_plus_llm"]
    left, right = st.columns(2)
    with left:
        st.markdown("##### LLM Only (cloud chat)")
        st.write(llm_only.get("text") or "*(no response text returned)*")
        st.caption(f"Response time: **{llm_only.get('elapsed_s')} sec** (measured)")
    with right:
        st.markdown("##### Tev1 + LLM")
        _render_decision_block(tev1)
        st.write(combined["explanation"] or "*(no explanation returned)*")
        st.caption(
            f"Tev1: **{combined['tev1_time_s']} sec** · LLM: **{combined['llm_time_s']} sec** · "
            f"Total: **{combined['total_time_s']} sec** (measured)"
        )
    st.caption("Tev1 decision confidence shown in the right column only — the cloud LLM "
               "supplies no confidence score, so none is displayed.")


# --- Results slots (plan 6.6): live in session_state so switching widgets above
# does not wipe the last analysis; the Analyze run writes real results into them.


st.session_state.setdefault("results", None)
st.session_state.setdefault("technical_details", None)  # raw API JSON (plan 7.4)

# --- Execution wiring (spec sections 6/11/13/14/26; plan 7.1-7.3).
if analyze:
    settings_missing = validate_settings()
    for message in settings_missing:
        st.error(message)  # spec section 19 wording, from settings — no key values
    if not scenario.strip():
        st.warning("Enter a scenario before analyzing.")
    elif custom_error:
        st.error(custom_error)  # invalid custom config → NO API call (plan 8.2f)
    elif demo_mode == "Custom" and execution_mode == "LLM Only":
        # Custom mode decides with Tev1 by definition (spec section 15) — running
        # LLM Only there would skip the decision entirely.
        st.error("Custom mode runs the decision model — pick 'Tev1 + LLM' or 'Compare Both'.")
    elif not settings_missing:
        details = {}  # raw request/response per leg; the key never enters (plan 7.4)

        def run_llm(tag: str, prompt: str) -> dict:
            raw = call_llm(prompt)
            details[tag] = {"prompt": prompt, "chat": raw}
            return summarize_llm(raw)

        try:
            tev1 = llm_only = llm_combined = None
            decision_request = None
            if demo_mode == "Custom":
                decision_request = {
                    "state": scenario,
                    "questions": {"decision": custom_mode.build_question(
                        custom_config, autofill_criteria=autofill_criteria)},
                }
                explanation_template = custom_mode.EXPLANATION_TEMPLATE
                combined_template = custom_mode.COMBINED_TEMPLATE
            else:
                decision_template, explanation_template, combined_template = \
                    MODE_TEMPLATES[demo_mode]
                if demo_mode == "General Decision":
                    # plan 8.3: editable categories + instruction (runtime rebuild);
                    # the expander stores comma text — parse to a list first.
                    # Edited choices need a full criteria map (probed contract),
                    # so autofill completes it with neutral descriptions.
                    gen_text = st.session_state.get("gen_categories") or ""
                    categories = [c.strip() for c in gen_text.split(",") if c.strip()]
                    questions = gen_build_questions(
                        categories=categories,
                        instructions=st.session_state.get("gen_instructions"),
                    )
                    for spec in questions.values():
                        if spec.get("type") == "choice":
                            spec["criteria"] = autofill_criteria(
                                spec["choices"], spec.get("criteria") or {})
                    decision_template = {
                        "state_preamble": decision_template["state_preamble"],
                        "questions": questions,
                    }

            if execution_mode in ("Tev1 + LLM", "Compare Both"):
                if decision_request is None:
                    decision_request = build_decision_request(decision_template, scenario)
                raw_tev1 = call_tev1(decision_request["state"], decision_request["questions"])
                tev1 = summarize_tev1(raw_tev1)
                details["tev1_request"] = {"state": decision_request["state"],
                                           "questions": decision_request["questions"]}
                details["tev1_response"] = raw_tev1

            if execution_mode == "LLM Only":
                llm_only = run_llm("llm_chat", explanation_template.format(user_input=scenario))

            if execution_mode == "Tev1 + LLM":
                llm_combined = run_llm(
                    "llm_chat", build_combined_prompt(combined_template, scenario, tev1)
                )

            if execution_mode == "Compare Both":  # both flows on the same input (plan 7.3)
                llm_only = run_llm("llm_only", explanation_template.format(user_input=scenario))
                llm_combined = run_llm(
                    "llm_combined", build_combined_prompt(combined_template, scenario, tev1)
                )

            st.session_state["results"] = {
                "user_input": scenario,
                "execution_mode": execution_mode,
                "demo_mode": demo_mode,
                "tev1": tev1,
                "llm_only": llm_only,
                "llm_combined": llm_combined,
            }
            st.session_state["technical_details"] = details
        except (Tev1Error, LlmError) as exc:
            st.error(str(exc))  # friendly typed error, no stack trace (spec sec 19)
        except Exception:  # noqa: BLE001 — last-resort guard in front of the user
            st.error("Unexpected error while analyzing. Check the terminal for details.")

# --- Results display (plan 7.5): every number shown is a value the APIs
# actually returned this run — measured times, no example values anywhere.
results = st.session_state["results"]
if results is not None:
    mode = results["execution_mode"]
    if mode == "LLM Only":
        _render_llm_card(results["llm_only"])
    elif mode == "Tev1 + LLM":
        _render_tev1_card(results["tev1"])
        _render_combined_card(results["tev1"], results["llm_combined"])
        times = build_comparison(results["tev1"], results["llm_combined"])["tev1_plus_llm"]
        st.markdown(
            "**Timing (measured)** — "
            f"Tev1: {times['tev1_time_s']} sec · Cloud LLM: {times['llm_time_s']} sec · "
            f"Total: {times['total_time_s']} sec"
        )  # spec section 20
    elif mode == "Compare Both":
        _render_compare(results["tev1"], results["llm_only"], results["llm_combined"])

    details = st.session_state["technical_details"]
    if details:
        with st.expander("Technical Details"):
            st.json(details)  # plan 7.4 — stored responses carry no key material

# --- Empty-state hero card (plan 6.5).
if results is None:
    st.info(
        "Enter a scenario, pick a Demo Mode and an Execution Mode, then select **Analyze**.\n\n"
        "**Tev1** (the decision model) produces a structured decision with confidence — "
        "the **Ollama Cloud LLM** produces a natural-language explanation. "
        "Compare both to see what each part of the workflow contributes."
    )