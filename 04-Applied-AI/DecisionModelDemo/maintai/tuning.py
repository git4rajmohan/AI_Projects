# Settings-page override hook (plan 14.3): run_decision reads these two values
# from st.session_state when a Streamlit session exists, .env defaults otherwise.
# No .env writes at runtime — persistence stays manual (spec1 §10 page 8).

import streamlit as st

from config.settings import SENSOR_FRESHNESS_MINUTES, TEV1_CONFIDENCE_REVIEW_THRESHOLD


def _effective(name: str, default):
    """override_<name> from the session (Settings page form), else default."""
    try:
        return st.session_state.get(f"override_{name}", default)
    except Exception:  # no Streamlit context (tests, CLI) — default applies
        return default


def tuning() -> tuple[float, float]:
    """(confidence_threshold, freshness_minutes) for decision runs."""
    return (_effective("confidence_threshold", TEV1_CONFIDENCE_REVIEW_THRESHOLD),
            _effective("freshness_minutes", SENSOR_FRESHNESS_MINUTES))