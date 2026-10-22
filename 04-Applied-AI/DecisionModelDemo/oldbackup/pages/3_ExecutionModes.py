# Execution-mode guide — read-only reference (tab 2) for the three Playgrounds
# execution modes. No API calls, no session-state coupling — safe to visit any time.
import streamlit as st

st.set_page_config(page_title="Execution Modes — Decision + LLM Playground", layout="wide")
st.title("Execution Modes — How Each Option Works")
st.caption("Reference for the three Execution Mode options on the Playgrounds page. "
           "Verified values come from real live runs (tev1:4b + glm-5.3-flash:cloud, 2026-10-02/19). "
           "No model calls on this page.")

EXAMPLE = "Customer was charged twice for the same subscription."

st.markdown("### The same scenario, three ways")
st.info(f'Running example (the Playgrounds pre-loaded input): **"{EXAMPLE}"**')

MODES = [
    ("LLM Only", "🔵", [
        ("What runs", "Just the cloud generative LLM (`glm-5.3-flash:cloud`). "
         "One HTTP call to `https://ollama.com/api/chat` — Tev1 is never invoked."),
        ("Flow", "`Scenario → LLM → natural-language answer`"),
        ("What you get", "A readable prose answer: diagnosis + recommended steps. "
         "Fine for reading, nothing is scored."),
        ("What you DON'T get", "No explicit decision, no confidence, no probabilities. "
         "The classification lives inside the text — you would have to parse prose to "
         "route a ticket or measure accuracy."),
        ("Timing shown", "LLM wall-clock time + real token counts (prompt/eval) when the API returns them."),
    ], "The classification is buried in free text — nothing is machine-verifiable."),
    ("Tev1 + LLM", "🟢", [
        ("What runs", "**Step 1** — the local decision model (`tev1:4b`, via local Ollama "
         "`/v1/systemone`) answers structured questions (Customer Support: intent / urgency / escalation). "
         "**Step 2** — its decision + confidence are passed to the LLM as *evidence* "
         "(`build_combined_prompt`); the LLM explains and is forbidden from inventing its own decision values."),
        ("Flow", "`Scenario → Tev1 (structured decision) → evidence → LLM explanation`"),
        ("What you get", "A decision card (choice + confidence % + per-option probability bars) "
         "**plus** an explanation grounded in that decision. Machine-readable AND readable."),
        ("Honesty rules", "Low-confidence results are flagged as uncertainty in the explanation — "
         "the LLM may not hide them; probabilities/confidence are rendered exactly as the API returned them."),
        ("Timing shown", "Tev1 time + LLM time, each measured separately."),
    ], "Verified live with this example: intent = duplicate_charge at 99.7% confidence "
       "(alternatives: cancel_subscription 0.06%, card_declined 0.006%, none 0.18%), "
       "urgency = high, escalation = no."),
    ("Compare Both", "🟠", [
        ("What runs", "BOTH flows independently on the same input: the LLM-only path "
         "AND the Tev1→LLM path (separate LLM calls, separate legs)."),
        ("Flow", "`Scenario → [LLM path] + [Tev1 → LLM path] → side-by-side columns`"),
        ("What you get", "Two columns showing exactly what the structured decision layer "
         "adds over free-form generation: decision & confidence vs. prose only, "
         "with both timings."),
        ("Use it when", "You're demoing the project's key message, or deciding which mode "
         "fits a real workflow before committing to one."),
        ("Cost note", "Slowest mode — it makes two LLM calls (plus one Tev1 call)."),
    ], "Same input, two philosophies: generation vs. scored decision + generation."),
]

st.markdown("### Mode details")
for title, emoji, rows, verdict in MODES:
    with st.expander(f"{emoji} {title}"):
        for label, body in rows:
            st.markdown(f"**{label}:** {body}")
        st.info(verdict)

st.markdown("### Side-by-side summary")
st.markdown(
    "| | LLM Only | Tev1 + LLM | Compare Both |\n"
    "|---|---|---|---|\n"
    "| Decision? | buried in text | **explicit choice** | explicit (right column) |\n"
    "| Confidence / probabilities? | none | **yes (+ per-option bars)** | yes (right column) |\n"
    "| Explanation? | yes | yes (evidence-grounded) | yes (both, different grounds) |\n"
    "| Timing? | LLM time | Tev1 + LLM time | all, per leg |\n"
    "| Batch-scoreable on 8503/Evaluation? | no | **yes (Tev1 leg)** | Tev1 leg only |\n"
    "| LLM calls | 1 | 1 | 2 |"
)
st.caption("The project's key message (README §27): decision models and generative LLMs "
           "solve different parts of an AI workflow — Tev1 answers *what is this and how sure "
           "are we*, the LLM answers *explain it well*. The Evaluation page batch-scores the "
           "Tev1 leg across saved scenarios (accuracy / confidence / time).")