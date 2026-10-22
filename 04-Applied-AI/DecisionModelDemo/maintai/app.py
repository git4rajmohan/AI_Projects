# MaintAI Decision Platform — app skeleton (spec1 §10; plan Phase 9).
# Run: streamlit run maintai/app.py

import requests
import streamlit as st

from config.settings import LLM_MODEL, OLLAMA_HOST, TEV1_MODEL

st.set_page_config(page_title="MaintAI Decision Platform", layout="wide",
                   page_icon="🏭")
st.title("MaintAI Decision Platform")
st.subheader("From machine signals to explainable maintenance decisions.")


@st.cache_data(ttl=30)  # same cheap-probe pattern as the playground (plan.md 6.2d)
def _service_status() -> dict:
    local = False
    try:
        local = requests.get(f"{OLLAMA_HOST}/api/version", timeout=2).ok
    except requests.exceptions.RequestException:
        pass
    return {"local": local}


with st.sidebar:
    st.header("Configuration")
    st.markdown("**Decision Model (Tev1)**")
    st.write(TEV1_MODEL)
    st.markdown("**Generative LLM**")
    st.write(LLM_MODEL or "*(not configured — set LLM_MODEL in .env)*")
    st.markdown("**Ollama Host**")
    st.write(OLLAMA_HOST)
    status = _service_status()
    st.caption(f"Local Ollama: {'🟢 up' if status['local'] else '🔴 down'}")

if not status["local"]:  # actionable startup hint (spec1 §17 step 7)
    st.error(f"Ollama is not reachable at {OLLAMA_HOST}. Start Ollama and run: "
             f"`ollama pull {TEV1_MODEL}`, then reload this page.")

st.info(
    "🧪 **Synthetic demonstration data.** All machine readings are simulated "
    "(data source labels say so). Thresholds are demonstration values, not "
    "universal engineering limits, and no outcome predicts actual failures.",
    icon="⚠️")

st.markdown("### Pages")
st.markdown(
    "- **Executive Dashboard** — fleet KPIs, alert trend, outcome mix\n"
    "- **Machine Monitoring** — select a machine, review sensor trends and run a decision analysis\n"
    "- **Decision Workbench** — full pipeline result: rules, Tev1 output, policy decision, explanation\n"
    "- **Machine Registry** — machines, threshold versions (role demo governs edits)\n"
    "- **Data Import** — upload sensor CSVs with preview + validation report\n"
    "- **Model Evaluation** — labelled synthetic batch: metrics + confusion matrix\n"
    "- **Settings** — configuration, connection checks, session overrides\n"
    "- **Maintenance History** — decision history per machine, record inspection outcomes\n"
)

if "maintai_db_ready" not in st.session_state:  # lazy one-time db check
    from maintai.database.connection import db_path
    st.session_state["maintai_db_ready"] = db_path().exists()
if not st.session_state["maintai_db_ready"]:
    st.warning("The database is not initialised yet. Run: `python -m maintai.seed`")