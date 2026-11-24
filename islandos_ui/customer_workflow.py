"""Cross-page context for the customer decision views.

05 and 06 are separate offline runs over a shared history. They already print the
same history hash at their demo defaults, but nothing compares the two surfaces
when a reader moves between them. This module adds that comparison and lets a
page-local CSV use the existing session-only handoff, without inventing a shared
run id or changing any model calculation.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, MutableMapping

import streamlit as st

from islandos_core.session_dataset import read_session_dataset, store_session_dataset

HISTORY_CONTEXT_KEY = "islandos_customer_history_context"

PAGE_META = {
    "decision_dashboard": {
        "title": "Compare operating policies and screen the investment",
        "step": 2,
        "path": "pages/05_Customer_Decision_Dashboard.py",
        "route": "Customer_Decision_Dashboard",
        "other": "joint_optimizer",
        "other_title": "Joint resource optimizer",
    },
    "joint_optimizer": {
        "title": "Forecast and coordinate a joint resource schedule",
        "step": 1,
        "path": "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
        "route": "Forecast_Led_Joint_Resource_Optimizer",
        "other": "decision_dashboard",
        "other_title": "Decision dashboard",
    },
}


def _valid_history_sha(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("history_sha256 must be a non-empty string")
    return value.strip()


def record_history_context(
    session_state: MutableMapping[str, Any],
    *,
    page: str,
    history_sha256: str,
    source_label: str,
) -> dict[str, str] | None:
    """Record this page's input identity and return the other page's last record."""
    if page not in PAGE_META:
        raise ValueError(f"unknown customer page: {page}")
    digest = _valid_history_sha(history_sha256)
    contexts = session_state.get(HISTORY_CONTEXT_KEY)
    if not isinstance(contexts, dict):
        contexts = {}
    other = PAGE_META[page]["other"]
    previous = contexts.get(other)
    contexts[page] = {
        "history_sha256": digest,
        "source_label": str(source_label),
    }
    session_state[HISTORY_CONTEXT_KEY] = contexts
    return previous if isinstance(previous, dict) else None


def compare_history_context(previous: dict[str, Any] | None, history_sha256: str) -> str:
    """Return ``no_previous``, ``match`` or ``mismatch`` for the other page."""
    digest = _valid_history_sha(history_sha256)
    if not previous:
        return "no_previous"
    other_digest = previous.get("history_sha256")
    if not isinstance(other_digest, str) or not other_digest:
        return "no_previous"
    return "match" if hmac.compare_digest(other_digest, digest) else "mismatch"


def render_customer_workflow(
    *,
    active_page: str,
    history_sha256: str,
    source_label: str,
    session_state: MutableMapping[str, Any] | None = None,
) -> None:
    """Render a compact step/next-step note and the cross-page input check."""
    if active_page not in PAGE_META:
        raise ValueError(f"unknown customer page: {active_page}")
    meta = PAGE_META[active_page]
    previous = record_history_context(
        st.session_state if session_state is None else session_state,
        page=active_page,
        history_sha256=history_sha256,
        source_label=source_label,
    )
    relation = compare_history_context(previous, history_sha256)
    other = PAGE_META[meta["other"]]

    with st.container(border=True):
        st.caption(f"CUSTOMER DECISION PATH · STEP {meta['step']} OF 3")
        st.markdown(f"**{meta['title']}**")
        if relation == "match":
            st.caption(
                f"Input match: the last {other['other_title']} used the same history SHA-256. "
                "The pages are still separate runs with different optimization and cost "
                "boundaries; do not compare their cost or saving totals as interchangeable."
            )
        elif relation == "mismatch":
            prior_source = previous.get("source_label") if previous else "an earlier run"
            st.warning(
                f"Input differs from the last {other['other_title']} ({prior_source}). "
                "The two outputs are not like-for-like. Use the same CSV or restore the "
                "same demo clock and assumptions before comparing them."
            )
        else:
            st.caption(
                f"Input check: open the {other['other_title']} in this browser session to "
                "compare this page's history SHA-256 with the other view."
            )
        st.markdown(f"[Open the {other['other_title']}](/{other['route']})")
        st.caption(
            "The device flexibility planner is an optional third check with fixed synthetic "
            "inputs; it is not a continuation of this history."
        )


def render_page_upload_handoff(
    *,
    page_key: str,
    file_name: str,
    payload: bytes,
    session_state: MutableMapping[str, Any] | None = None,
) -> None:
    """Offer the existing session handoff for a CSV uploaded on 05 or 06."""
    if page_key not in PAGE_META:
        raise ValueError(f"unknown customer page: {page_key}")
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("uploaded CSV payload must be non-empty bytes")
    target_state = st.session_state if session_state is None else session_state
    digest = hashlib.sha256(payload).hexdigest()
    current, _ = read_session_dataset(target_state)
    if current and hmac.compare_digest(str(current.get("sha256", "")), digest):
        st.caption(
            "This file is already shared for the other customer view in this browser session. "
            "The page-local upload remains the input used here."
        )
        return

    st.caption(
        "This upload is local to this page. Share it once to use the same bytes on the other "
        "customer view; the handoff stays in this browser session only."
    )
    if st.button(
        "Share this CSV with the other customer view",
        key=f"share_customer_csv_{page_key}",
    ):
        try:
            stored = store_session_dataset(
                target_state,
                file_name=file_name,
                payload=payload,
                source_type="customer_provided",
            )
        except ValueError as exc:
            st.error(f"Could not share this CSV: {exc}")
        else:
            st.success(
                "CSV shared for the other customer view in this session. "
                f"SHA-256: {stored['sha256'][:16]}…"
            )
