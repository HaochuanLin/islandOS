import hashlib
import json
import sqlite3

import pytest

from islandos_core.shadow_evidence import ShadowEvidenceStore
from islandos_core.shadow_mode import compare_shadow_run


def _report(observation_id="obs-1"):
    return compare_shadow_run(
        {"recommendation_id": "rec-1", "created_at_utc": "2026-11-13T10:00:00Z",
         "signals": {"battery_kw": {"value": 4.0, "unit": "kW"}}},
        {"observation_id": observation_id, "timestamp_utc": "2026-11-13T10:04:00Z",
         "signals": {"battery_kw": {"value": 4.1, "unit": "kW", "tolerance": 0.5}}},
        evaluated_at_utc="2026-11-13T10:05:00Z",
    )


def test_append_and_verify_hash_chain(tmp_path):
    store = ShadowEvidenceStore(tmp_path / "shadow.sqlite3")
    first = store.append("site-A", _report())
    second = store.append("site-A", _report("obs-2"))
    assert first["previous_hash"] == "0" * 64
    assert second["previous_hash"] == first["chain_hash"]
    assert store.verify_chain()["valid"] is True
    assert store.verify_chain()["records_checked"] == 2
    assert len(store.list_recent("site-A")) == 2


def test_duplicate_identity_is_rejected(tmp_path):
    store = ShadowEvidenceStore(tmp_path / "shadow.sqlite3")
    store.append("site-A", _report())
    with pytest.raises(ValueError, match="duplicate"):
        store.append("site-A", _report())


def test_report_digest_and_write_invariants_are_required(tmp_path):
    store = ShadowEvidenceStore(tmp_path / "shadow.sqlite3")
    report = _report()
    report["device_write_authorized"] = True
    with pytest.raises(ValueError, match="prohibit"):
        store.append("site-A", report)

    report = _report()
    report["status"] = "within_tolerance"
    with pytest.raises(ValueError, match="digest"):
        store.append("site-A", report)


def test_chain_verification_detects_record_tampering(tmp_path):
    path = tmp_path / "shadow.sqlite3"
    store = ShadowEvidenceStore(path)
    store.append("site-A", _report())
    with sqlite3.connect(path) as db:
        db.execute("UPDATE shadow_evidence SET status='blocked' WHERE id=1")
    result = store.verify_chain()
    assert result["valid"] is False
    assert any("report hash mismatch" in error for error in result["errors"])


def test_site_and_limit_validation(tmp_path):
    store = ShadowEvidenceStore(tmp_path / "shadow.sqlite3")
    with pytest.raises(ValueError):
        store.append("", _report())
    with pytest.raises(ValueError):
        store.list_recent("site-A", 0)
