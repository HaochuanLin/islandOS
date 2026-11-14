"""Session-scoped handoff for a validated site CSV between Streamlit pages.

The payload lives only in the current Streamlit browser session. It is not
persisted to SQLite, a project workspace, or a long-term server data store.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, MutableMapping

SESSION_DATASET_KEY = "islandos_session_site_dataset"


def store_session_dataset(
    session_state: MutableMapping[str, Any],
    *,
    file_name: str,
    payload: bytes,
    source_type: str,
) -> dict[str, Any]:
    """Store an uploaded CSV in the current session and return safe metadata."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("dataset payload must be non-empty bytes")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name must be a non-empty string")
    if not isinstance(source_type, str) or not source_type.strip():
        raise ValueError("source_type must be a non-empty string")

    digest = hashlib.sha256(payload).hexdigest()
    session_state[SESSION_DATASET_KEY] = {
        "file_name": file_name.strip(),
        "payload": payload,
        "sha256": digest,
        "source_type": source_type.strip(),
        "byte_count": len(payload),
    }
    return {"sha256": digest, "byte_count": len(payload), "file_name": file_name.strip()}


def get_session_dataset(
    session_state: MutableMapping[str, Any],
) -> dict[str, Any] | None:
    """Return a verified copy of the current session dataset, if present."""
    record = session_state.get(SESSION_DATASET_KEY)
    if record is None:
        return None
    if not isinstance(record, dict):
        raise ValueError("session dataset record is malformed")

    payload = record.get("payload")
    digest = record.get("sha256")
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("session dataset payload is missing or invalid")
    if not isinstance(digest, str) or not hmac.compare_digest(
        hashlib.sha256(payload).hexdigest(), digest
    ):
        raise ValueError("session dataset SHA-256 verification failed")
    return dict(record)


def clear_session_dataset(session_state: MutableMapping[str, Any]) -> None:
    """Remove the session-scoped dataset handoff."""
    session_state.pop(SESSION_DATASET_KEY, None)
