# Model Evaluation page (spec1 §10 page 7; plan Phase 13): batch-run the
# generated labelled cases with a mocked TEV1, show sklearn metrics + confusion
# matrix (plotly heatmap), per-machine-type breakdown, export CSV.
# Standing rule: these are SYNTHETIC demonstration results, never production
# performance (spec1 §13).

import io

import pandas as pd
import plotly.express as px
import streamlit as st

from maintai.database import repository as repo
from maintai.database.connection import get_conn, init_db
from maintai.evaluation_service import (generate_cases, metrics, run_evaluation,
                                        to_csv_string)

st.set_page_config(page_title="Model Evaluation — MaintAI", layout="wide",
                   page_icon="📈")
st.title("Model Evaluation")
st.error(
    "🧪 **Synthetic demonstration results — never production performance.** "
    "Cases, labels and model replies are generated; nothing here measures "
    "real-world behaviour.", icon="⚠️")

conn = get_conn()
init_db(conn)

col_gen, col_run = st.columns([2, 1])
per_type = col_gen.number_input("Cases per scenario", 20, 200, 20, step=5,
                                help="5 scenarios × N = total cases; every "
                                     "10th case is reserved holdout.")
run = col_run.button("Run evaluation", type="primary")
if run or "eval_rows" in st.session_state:
    if run or "eval_rows" not in st.session_state:
        cases = generate_cases(per_type=int(per_type))
        with st.spinner("Running the labelled batch…"):
            st.session_state["eval_rows"] = run_evaluation(cases["tuning"])
            st.session_state["eval_holdout_ids"] = [c["case_id"]
                                                    for c in cases["holdout"]]
    rows = st.session_state["eval_rows"]
    m = metrics(rows)

    top = st.columns(4)
    top[0].metric("Labelled test cases", m["n_cases"])
    top[1].metric("Accuracy", f"{m['accuracy'] * 100:.1f}%" if m["accuracy"] is not None else "n/a")
    top[2].metric("Human-review rate", f"{m['human_review_rate'] * 100:.1f}%")
    top[3].metric("Unavailable/invalid rate",
                  f"{m['unavailable_or_invalid_rate'] * 100:.1f}%")

    left, right = st.columns(2)
    with left:  # per-class precision / recall
        st.markdown("##### Per-class precision / recall")
        st.dataframe(pd.DataFrame([
            {"Action": label,
             "Precision": m["per_class_precision"][label],
             "Recall": m["per_class_recall"][label]}
            for label in m["labels"]]), hide_index=True, use_container_width=True)

    with right:  # confusion matrix heatmap
        st.markdown("##### Confusion matrix (expected × final action)")
        cm = m["confusion_matrix"]
        fig = px.imshow(cm, x=[f"→{a}" for a in m["labels"]],
                        y=[f"✓{a}" for a in m["labels"]],
                        text_auto=True, color_continuous_scale="Blues")
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320)
        st.plotly_chart(fig, use_container_width=True)

    ops = st.columns(3)
    ops[0].metric("TEV1 avg latency (measured)",
                  f"{m['avg_tev1_latency_ms']:.0f} ms"
                  if m["avg_tev1_latency_ms"] is not None else "n/a")
    ops[1].metric("LLM avg latency",
                  "n/a (no LLM in the batch run)")
    st.markdown("##### Results by machine type")
    st.dataframe(pd.DataFrame([
        {"Machine type": k, "Accuracy": v} for k, v in m["by_machine_type"].items()
    ]), hide_index=True, use_container_width=True)

    st.markdown("##### Per-case results")
    export = to_csv_string(rows)
    st.dataframe(pd.read_csv(io.StringIO(export)),
                 hide_index=True, use_container_width=True)
    st.download_button("Export results CSV", data=export,
                       file_name="maintai_eval_results.csv", mime="text/csv")
    holdout_ids = st.session_state.get("eval_holdout_ids", [])
    if holdout_ids:
        st.caption("Holdout slice excluded from this run: "
                   + ", ".join(holdout_ids))
    repo.record_audit(conn, "dashboard", "evaluation_run", "system",
                      "model_evaluation",
                      {"n_cases": m["n_cases"], "accuracy": m["accuracy"],
                       "human_review_rate": m["human_review_rate"]})
    conn.commit()
else:
    st.info("Set the batch size and press **Run evaluation**. TEV1 replies are "
            "canned (mocked) for this demo; the pipeline (validation → rules → "
            "policy) is the real one.")