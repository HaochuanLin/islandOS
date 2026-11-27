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
import json
from collections.abc import Mapping
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


def _valid_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _valid_history_sha(value: Any) -> str:
    return _valid_text(value, "history_sha256")


def _valid_site_digest(value: Any) -> str:
    return _valid_text(value, "site_digest")


def _valid_hour_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("hour_count must be a positive integer")
    return value


def _valid_units(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("units must be a non-empty mapping")
    normalized: dict[str, str] = {}
    for signal, unit in value.items():
        signal_name = _valid_text(signal, "units signal")
        unit_name = _valid_text(unit, f"units[{signal_name}]")
        normalized[signal_name] = unit_name
    return normalized


def _valid_page_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("page_settings must be a mapping")
    try:
        settings = dict(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"page_settings must be a plain mapping: {exc}") from exc
    try:
        json.dumps(
            settings,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"page_settings must be JSON-serializable: {exc}") from exc
    return settings


def build_input_fingerprint(
    *,
    page: str,
    history_sha256: str,
    site_digest: str,
    units: Mapping[str, str],
    hour_count: int,
    currency: str,
    page_settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a stable identity for one customer page's complete input.

    ``fingerprint_sha256`` covers the inputs 05 and 06 genuinely share: history,
    site configuration, signal units, window length and currency.  The page-level
    settings are stored and hashed separately because the two pages do not expose
    the same knobs; folding them into the shared digest would turn every
    cross-page comparison into a false mismatch.
    """
    if page not in PAGE_META:
        raise ValueError(f"unknown customer page: {page}")
    shared_payload = {
        "history_sha256": _valid_history_sha(history_sha256),
        "site_digest": _valid_site_digest(site_digest),
        "units": _valid_units(units),
        "hour_count": _valid_hour_count(hour_count),
        "currency": _valid_text(currency, "currency"),
    }
    settings = _valid_page_settings(page_settings)
    shared_canonical = json.dumps(
        shared_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    settings_canonical = json.dumps(
        settings,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return {
        "page": page,
        **shared_payload,
        "page_settings": settings,
        "page_settings_sha256": hashlib.sha256(
            settings_canonical.encode("utf-8")
        ).hexdigest(),
        "fingerprint_sha256": hashlib.sha256(
            shared_canonical.encode("utf-8")
        ).hexdigest(),
    }


def compare_input_fingerprints(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> str:
    """Return ``no_previous``, ``match`` or ``mismatch`` for two fingerprints."""
    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        return "no_previous"
    if not previous.get("fingerprint_sha256") and isinstance(
        previous.get("fingerprint"), Mapping
    ):
        previous = previous["fingerprint"]
    previous_digest = previous.get("fingerprint_sha256")
    current_digest = current.get("fingerprint_sha256")
    if (
        not isinstance(previous_digest, str)
        or not previous_digest
        or not isinstance(current_digest, str)
        or not current_digest
    ):
        return "no_previous"
    return "match" if hmac.compare_digest(previous_digest, current_digest) else "mismatch"


def record_history_context(
    session_state: MutableMapping[str, Any],
    *,
    page: str,
    history_sha256: str,
    source_label: str,
    fingerprint: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Record this page's input identity and return the other page's last record."""
    if page not in PAGE_META:
        raise ValueError(f"unknown customer page: {page}")
    digest = _valid_history_sha(history_sha256)
    contexts = session_state.get(HISTORY_CONTEXT_KEY)
    if not isinstance(contexts, dict):
        contexts = {}
    other = PAGE_META[page]["other"]
    previous = contexts.get(other)
    record: dict[str, Any] = {
        "history_sha256": digest,
        "source_label": str(source_label),
    }
    if fingerprint is not None:
        if not isinstance(fingerprint, Mapping):
            raise ValueError("fingerprint must be a mapping")
        fingerprint_digest = fingerprint.get("fingerprint_sha256")
        if not isinstance(fingerprint_digest, str) or not fingerprint_digest.strip():
            raise ValueError("fingerprint must contain a non-empty fingerprint_sha256")
        fingerprint_page = fingerprint.get("page")
        if fingerprint_page is not None and fingerprint_page != page:
            raise ValueError(
                f"fingerprint page {fingerprint_page!r} does not match {page!r}"
            )
        stored_fingerprint = dict(fingerprint)
        stored_fingerprint["fingerprint_sha256"] = fingerprint_digest.strip()
        record["fingerprint"] = stored_fingerprint
    contexts[page] = record
    session_state[HISTORY_CONTEXT_KEY] = contexts
    return previous if isinstance(previous, dict) else None


def compare_history_context(
    previous: dict[str, Any] | None,
    history_sha256: str,
    *,
    fingerprint: Mapping[str, Any] | None = None,
) -> str:
    """Return ``no_previous``, ``match`` or ``mismatch`` for the other page."""
    if fingerprint is not None:
        return compare_input_fingerprints(previous, fingerprint)
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
    fingerprint: Mapping[str, Any] | None = None,
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
        fingerprint=fingerprint,
    )
    relation = compare_history_context(
        previous,
        history_sha256,
        fingerprint=fingerprint,
    )
    peer_name = meta["other_title"]

    with st.container():
        if relation == "match":
            if fingerprint is not None:
                st.caption(
                    f"Input match: the last {peer_name} used the same shared input "
                    "fingerprint. The pages are still separate runs with different "
                    "optimization and cost boundaries; do not compare their cost or "
                    "saving totals as interchangeable."
                )
            else:
                st.caption(
                    f"Input match: the last {peer_name} used the same history "
                    "SHA-256. The pages are still separate runs with different optimization "
                    "and cost boundaries; do not compare their cost or saving totals as "
                    "interchangeable."
                )
        elif relation == "mismatch":
            prior_source = previous.get("source_label") if previous else "an earlier run"
            if fingerprint is not None:
                st.warning(
                    f"Input fingerprint differs from the last {peer_name} "
                    f"({prior_source}). The two outputs are not like-for-like. Use the same "
                    "CSV, site assumptions and shared input window before comparing them."
                )
            else:
                st.warning(
                    f"Input differs from the last {peer_name} ({prior_source}). "
                    "The two outputs are not like-for-like. Use the same CSV or restore the "
                    "same demo clock and assumptions before comparing them."
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
