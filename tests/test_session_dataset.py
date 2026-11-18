from __future__ import annotations

import hashlib

import pytest

from islandos_core.session_dataset import (
    SESSION_DATASET_KEY,
    clear_session_dataset,
    get_session_dataset,
    store_session_dataset,
)


def test_session_dataset_round_trip_and_hash_verification():
    state = {}
    payload = b"timestamp_utc,pv_power_kw\n2026-01-01T00:00:00Z,1\n"

    metadata = store_session_dataset(
        state, file_name="site.csv", payload=payload, source_type="customer_provided"
    )
    record = get_session_dataset(state)

    assert record is not None
    assert record["payload"] == payload
    assert record["file_name"] == "site.csv"
    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["sha256"] == metadata["sha256"]


def test_session_dataset_rejects_modified_payload():
    state = {}
    store_session_dataset(
        state, file_name="site.csv", payload=b"original", source_type="customer_provided"
    )
    state[SESSION_DATASET_KEY]["payload"] = b"modified"

    with pytest.raises(ValueError, match="SHA-256"):
        get_session_dataset(state)


def test_session_dataset_rejects_empty_payload():
    with pytest.raises(ValueError, match="non-empty"):
        store_session_dataset(
            {}, file_name="empty.csv", payload=b"", source_type="customer_provided"
        )


def test_clear_session_dataset_removes_only_handoff_record():
    state = {"keep": "value"}
    store_session_dataset(
        state, file_name="site.csv", payload=b"csv", source_type="customer_provided"
    )

    clear_session_dataset(state)

    assert get_session_dataset(state) is None
    assert state == {"keep": "value"}
