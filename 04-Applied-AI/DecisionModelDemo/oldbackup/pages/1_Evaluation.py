# Evaluation page — optional evaluation section (spec section 21; plan Phase 9).
# Lives in pages/ so Streamlit registers it automatically as a second page.
# Runs Tev1 only — no cloud LLM call happens on this page.
import pandas as pd
import streamlit as st

import services.evaluation as ev

MODES = ("Customer Support", "QA / Testing", "General Decision", "Custom")

st.set_page_config(page_title="Evaluation — Decision + LLM Playground", layout="wide")
st.title("Evaluation")
st.caption("Run the saved scenarios through the decision model and score the answers.")

# --- Capture (plan 9.3): pre-fills from the last analysis on the main page —
# session_state is shared across pages of the same browser session.
with st.expander("Add current scenario to evaluation set"):
    last = st.session_state.get("results")
    if not last or not (last.get("user_input") or "").strip():
        st.info("Run an analysis on the Playgrounds page first.")
    elif last.get("demo_mode") == "Custom":
        # Custom rows need their decision config; the capture would produce
        # rows that error at run time, so it is refused here (honest ceiling).
        st.info("Custom-mode scenarios need their decision config too — add them "
                "to evaluation/scenarios.json directly (with a 'custom' object).")
    else:
        st.text_area("Scenario input", key="capture_input", value=last["user_input"])
        st.selectbox(
            "Demo Mode", MODES, key="capture_mode",
            index=MODES.index(last["demo_mode"]) if last.get("demo_mode") in MODES else 0,
        )
        tev_last = last.get("tev1") or {}
        st.text_input(
            "Expected decision", key="capture_expected",
            value=tev_last.get("decision") or "",
            help="Pre-filled with the Tev1 decision from the last run — review it before saving.")
        if st.button("Add to evaluation set", key="capture_add"):
            rows, corrupt_msg = ev.load_scenarios_safe()
            if corrupt_msg:
                st.error(corrupt_msg)  # corrupt file — refuse capture, keep the message up
            else:
                rows.append({
                    "mode": st.session_state["capture_mode"],
                    "input": (st.session_state["capture_input"] or "").strip(),
                    "expected": (st.session_state["capture_expected"] or "").strip() or None,
                    "confidence_threshold": None,
                })
                try:  # same friendly guard as the Run path (no raw traceback)
                    ev.save_scenarios(rows)
                    st.success("Added to evaluation/scenarios.json — shown in the table below.")
                except OSError as exc:
                    st.error(f"Could not write evaluation/scenarios.json ({exc}).")

# --- Saved scenarios (plan 9.1 seeded spec-17 style inputs; editable here).
st.markdown("### Saved scenarios")
scenarios, corrupt_msg = ev.load_scenarios_safe()  # corrupt/hand-edited JSON -> friendly error + []
if corrupt_msg:
    st.error(corrupt_msg)  # shown above the (empty) table; Run stays disabled below
seed = pd.DataFrame([
    {
        "mode": r.get("mode") or "",
        "input": r.get("input") or "",
        "expected": r.get("expected") or "",
        "own_threshold": r.get("confidence_threshold"),
    }
    for r in scenarios
])
edited = st.data_editor(
    seed,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "mode": st.column_config.SelectboxColumn("mode", options=MODES),
        "input": st.column_config.TextColumn("input", width="large"),
        "expected": st.column_config.TextColumn(
            "expected", help="Leave empty to keep the row unscored."),
        "own_threshold": st.column_config.NumberColumn(
            "own threshold (0-1)", min_value=0.0, max_value=1.0, step=0.05,
            help="Flag answers strictly below this confidence as uncertain (spec section 19)."),
    },
    width="stretch",
)
if st.button("Save scenarios to evaluation/scenarios.json"):
    # ponytail: editor round-trips mode/input/expected/own_threshold only; a
    # hand-added Custom row's "custom" dict survives via (mode, input) match.
    originals = {(r.get("mode"), r.get("input")): r for r in scenarios}
    persisted, dropped = [], 0
    for _, r in edited.iterrows():
        mode = str(r.get("mode") or "").strip()
        text = str(r.get("input") or "").strip()
        if not text or mode not in MODES:
            dropped += 1
            continue
        row = {
            "mode": mode,
            "input": text,
            "expected": str(r.get("expected") or "").strip() or None,
            "confidence_threshold": (
                float(r["own_threshold"]) if pd.notna(r["own_threshold"]) else None),
        }
        kept = originals.get((mode, text))
        if kept and isinstance(kept.get("custom"), dict):
            row["custom"] = kept["custom"]
        persisted.append(row)
    try:  # same friendly guard as the capture path (no raw traceback)
        ev.save_scenarios(persisted)
    except OSError as exc:
        st.error(f"Could not write evaluation/scenarios.json ({exc}).")
    else:
        scenarios = persisted
        st.success(f"Saved {len(persisted)} scenario(s)."
                   + (f" Dropped {dropped} incomplete row(s)." if dropped else ""))

# --- Run (plan 9.2a-b): batch through Tev1 with live progress. The file is
# the run source — save edits first if they should be part of the run.
st.markdown("### Run")
if st.button("Run evaluation", type="primary", disabled=not scenarios):
    to_run, corrupt_msg = ev.load_scenarios_safe()
    if corrupt_msg:
        st.error(corrupt_msg)  # save edits first cannot help against corrupt JSON
    else:
        with st.status("Running scenarios through Tev1...", expanded=True) as status:
            outcomes = [ev.run_scenario(row) for row in to_run]
            for i, (row, out) in enumerate(zip(to_run, outcomes), 1):
                label = f"{i}. {(row.get('input') or '')[:60]}"
                if out.get("error"):
                    st.write(f":red[{label} — {out['error']}]")
                else:
                    conf = out.get("confidence")
                    st.write(f"{label} → **{out.get('actual')}**"
                             + (f" ({conf * 100:.1f}%)" if isinstance(conf, (int, float)) else ""))
            status.update(label="Evaluation complete", state="complete")
        st.session_state["eval_display"] = ev.build_rows(to_run, outcomes)
        st.session_state["eval_metrics"] = ev.metrics(st.session_state["eval_display"])
if not scenarios:
    st.caption("No scenarios saved yet — save rows in the table above.")

display = st.session_state.get("eval_display")
aggregate = st.session_state.get("eval_metrics")
if aggregate:
    # Spec section 21: never claim high confidence proves correctness.
    st.warning(
        "Accuracy compares against saved expected values. A higher confidence does "
        "NOT automatically mean higher correctness — confidence is not proof."
    )
    cols = st.columns(3)
    cols[0].metric(
        "Decision Accuracy",
        f"{aggregate['accuracy_pct']}%" if aggregate["accuracy_pct"] is not None else "not scored",
    )
    cols[0].caption(f"{aggregate['correct']} of {aggregate['scored']} scored rows")
    cols[1].metric(
        "Average Confidence",
        f"{aggregate['avg_confidence_pct']}%"
        if aggregate["avg_confidence_pct"] is not None else "not returned",
    )
    cols[2].metric(
        "Average Response Time",
        f"{aggregate['avg_response_time_s']} sec"
        if aggregate["avg_response_time_s"] is not None else "not returned",
    )
    st.dataframe(pd.DataFrame(display), width="stretch")

    # Uncertain rows = below their threshold (spec section 19 wording).
    uncertain = [r for r in display if r["low_confidence"]]
    if uncertain:
        st.caption("Uncertain rows (below their threshold): "
                   + f"{', '.join(str(i + 1) for i, r in enumerate(display) if r['low_confidence'])}")

    left, right = st.columns(2)
    left.download_button(
        "Download results CSV",
        data=ev.to_csv_string(display),
        file_name="evaluation_results.csv",
        mime="text/csv",
    )
    if right.button("Save results CSV to evaluation/exports/"):
        try:  # disk errors must show a friendly message, not a traceback
            path = ev.write_export(display)
        except OSError as exc:
            right.error(f"Could not write the export file ({exc}).")
        else:
            right.success(f"Saved to {path}")