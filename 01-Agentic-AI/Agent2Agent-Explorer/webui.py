"""Web UI for the Remote A2A Agent Explorer (screens A-E from instructions §11).

Run: .venv\\Scripts\\python.exe -m streamlit run webui.py
Local agents need ALLOW_LOCAL_AGENTS=true in the environment before launch.
"""
import asyncio

import streamlit as st

from directories.registry_provider import A2ARegistryProvider, resolve_page_url
from remote_agents.agent_store import AgentStore
from remote_agents.card_fetcher import CardFetchError, fetch_card_json
from remote_agents.card_validator import CardValidationError, summarize_card, validate_card
from remote_agents.endpoint_validator import EndpointReport, check_endpoint
from remote_agents.remote_client import RemoteAuthError, send_task
from remote_agents.url_safety import UnsafeUrlError

st.set_page_config(page_title="Remote A2A Agent Explorer", page_icon="🛰️", layout="wide")

KNOWN_ERRORS = (UnsafeUrlError, CardFetchError, CardValidationError, RemoteAuthError)

# ponytail: AgentStore per rerun; sqlite open is cheap and avoids cross-thread issues
store = AgentStore("agents.db")


def status_icon(value: str) -> str:
    good = ("VALID", "SUPPORTED", "REACHABLE", "SUCCESS", "COMPLETED")
    neutral = ("NOT CHECKED", "NOT TESTED", "NONE REQUIRED", "UNKNOWN")
    if value.startswith(good):
        return "✅"
    if value.startswith(neutral) or value.startswith("REQUIRED"):
        return "⚪"
    return "❌"


def show_report(report: EndpointReport) -> None:
    cols = st.columns(5)
    for col, (label, value) in zip(
        cols,
        [
            ("Agent Card", report.card),
            ("Protocol", report.protocol),
            ("Endpoint", report.endpoint),
            ("Authentication", report.authentication),
            ("Task execution", report.task_execution),
        ],
    ):
        col.markdown(f"**{label}**")
        col.markdown(f"{status_icon(value)} {value.split(' - ')[0]}")
        if " - " in value:
            col.caption(value.split(" - ", 1)[1])


def discover_card(url: str):
    """Fetch + validate; stash in session for the Save button."""
    try:
        vc = validate_card(fetch_card_json(url), url)
    except CardFetchError:
        card_url = resolve_page_url(url)  # registry agent page -> its card URL
        if not card_url:
            raise
        vc = validate_card(fetch_card_json(card_url), card_url)
    st.session_state["discovered"] = vc
    st.session_state["discovered_report"] = check_endpoint(vc)


st.title("🛰️ Remote A2A Agent Explorer")
tab_discover, tab_task, tab_saved = st.tabs(["🔍 Discover", "📤 Send Task", "💾 Saved Agents"])

# --- Screen A/B/C: Discover ---
with tab_discover:
    left, right = st.columns(2)
    with left:
        st.subheader("Search public directory")
        query = st.text_input(
            "Search a2aregistry.org (empty = list every registered agent)",
            placeholder="e.g. research",
        )
        if st.button("Search"):
            with st.spinner("Searching the registry..."):
                try:
                    st.session_state["candidates"] = A2ARegistryProvider().search(query)
                except KNOWN_ERRORS as exc:
                    st.error(str(exc))
        candidates = st.session_state.get("candidates")
        if candidates is not None:
            if candidates:
                st.caption(f"✅ {len(candidates)} agent(s)" + (f" matching {query!r}" if query else " (full registry)"))
            else:
                st.info("No matching agents. Try another word, or paste an Agent Card URL on the right.")
        for i, c in enumerate(candidates or []):
            with st.container(border=True):
                st.markdown(f"**{c.name}** — {c.provider or 'unknown provider'}")
                st.caption(c.description[:200])
                st.caption(f"Skills: {', '.join(c.skills) or '-'}")
                if st.button("Inspect Agent Card", key=f"inspect{i}"):
                    try:
                        discover_card(c.card_url)
                    except KNOWN_ERRORS as exc:
                        st.error(str(exc))
    with right:
        st.subheader("Or enter an Agent Card URL")
        url = st.text_input("Agent Card URL", placeholder="https://remote-agent.example/.well-known/agent-card.json")
        if st.button("Discover Agent", disabled=not url):
            try:
                discover_card(url)
            except KNOWN_ERRORS as exc:
                st.error(str(exc))

    if vc := st.session_state.get("discovered"):
        st.divider()
        st.subheader(f"Agent Card: {vc.card.name}")
        show_report(st.session_state["discovered_report"])
        st.code(summarize_card(vc), language=None)
        if st.button("💾 Save this agent"):
            agent_id = store.save_agent(vc)
            st.success(f"Saved as agent #{agent_id}. See the Saved Agents tab.")

# --- Screen D: Send Task ---
with tab_task:
    agents = store.list_agents()
    if not agents:
        st.info("No saved agents yet — discover and save one first.")
    else:
        choice = st.selectbox(
            "Remote agent",
            agents,
            format_func=lambda a: f"#{a['id']} {a['name']} ({'trusted' if a['trusted'] else 'untrusted'})",
        )
        task_text = st.text_area("Task", placeholder="Research the main features of Playwright")
        token = st.text_input(
            "Bearer token (only if the agent requires it — kept in this session only)",
            type="password",
        )
        if st.button("Send A2A Task", type="primary", disabled=not task_text):
            states: list[str] = []
            try:
                with st.spinner(f"Sending task to '{choice['name']}' ..."):
                    vc = validate_card(fetch_card_json(choice["agent_card_url"]), choice["agent_card_url"])
                    result = asyncio.run(
                        send_task(vc, task_text, bearer_token=token or None, progress=states.append)
                    )
                store.record_task(choice["id"], task_text, result)
                st.caption("Task status: " + (" → ".join(states) or result.state))
                kind = (
                    "message-only reply (no task ID)"
                    if result.message_only()
                    else f"task ID `{result.task_id}`"
                )
                st.markdown(f"{status_icon(result.state)} **{result.state}** — remote agent "
                            f"**{result.agent_name}**, {kind}")
                if result.is_paid_offer():
                    st.warning("💳 This agent offered a **paid service** (e.g. x402 micropayment). "
                               "Nothing was charged or sent — payment integration is out of scope for this MVP.")
                st.markdown("**Result (untrusted remote output, shown verbatim):**")
                for t in result.texts:
                    st.text(t)
                for d in result.data:
                    st.json(dict(d) if hasattr(d, "keys") else d)
                for a in result.artifacts:
                    st.caption(f"artifact: {a} (not downloaded)")
            except KNOWN_ERRORS as exc:
                st.error(str(exc))

# --- Screen E: Saved agents ---
with tab_saved:
    agents = store.list_agents()
    if not agents:
        st.info("Nothing saved yet.")
    for a in agents:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
            c1.markdown(f"**#{a['id']} {a['name']}** — auth: {a['auth_scheme'] or 'none'}")
            c1.caption(f"endpoint: {a['service_endpoint']}")
            c1.caption(f"card: {a['agent_card_url']}  ·  last validated: {a['last_validated_at']}")
            trusted = c2.toggle("Trusted", value=bool(a["trusted"]), key=f"trust{a['id']}")
            if trusted != bool(a["trusted"]):
                store.set_trusted(a["id"], trusted)
                st.rerun()
            if c3.button("Refresh card", key=f"refresh{a['id']}"):
                try:
                    vc = validate_card(fetch_card_json(a["agent_card_url"]), a["agent_card_url"])
                    store.save_agent(vc)
                    st.rerun()
                except KNOWN_ERRORS as exc:
                    st.error(str(exc))
            if c4.button("🗑️ Remove", key=f"remove{a['id']}"):
                store.delete_agent(a["id"])
                st.rerun()
            history = store.task_history(a["id"])
            if history:
                with st.expander(f"Task history ({len(history)})"):
                    for h in history:
                        st.markdown(
                            f"`{h['completed_at']}` {status_icon(h['task_state'])} "
                            f"**{h['task_state']}** task `{h['task_id'] or '?'}`"
                        )
                        if h["result_summary"]:
                            st.caption(h["result_summary"][:200])
