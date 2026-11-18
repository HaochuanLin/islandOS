from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.telemetry_adapter_contract import normalize_telemetry_batch


def _payloads(now):
    stamp = (now - timedelta(seconds=5)).isoformat()
    return [
        {"signal_id": "load_kw", "value": 12.5, "unit": "kW", "timestamp": stamp, "quality": "good"},
        {"signal_id": "battery_soc", "value": 70.0, "unit": "%", "timestamp": stamp, "quality": "good"},
    ]


def test_batch_normalization_is_stable_and_provenance_hashed():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = normalize_telemetry_batch(
        _payloads(now), source_id="test-gateway",
        expected_units={"load_kw": "kW", "battery_soc": "%"}, received_at=now,
    )
    second = normalize_telemetry_batch(
        _payloads(now), source_id="test-gateway",
        expected_units={"load_kw": "kW", "battery_soc": "%"}, received_at=now,
    )
    assert first.schema_version == "1.0"
    assert first.batch_sha256 == second.batch_sha256
    assert len(first.readings) == 2


def test_batch_rejects_missing_signal_and_duplicate_signal_timestamp():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="incomplete"):
        normalize_telemetry_batch(
            _payloads(now)[:1], source_id="test-gateway",
            expected_units={"load_kw": "kW", "battery_soc": "%"}, received_at=now,
        )
    payloads = _payloads(now)
    payloads[1]["signal_id"] = "load_kw"
    payloads[1]["unit"] = "kW"
    with pytest.raises(ValueError, match="duplicate"):
        normalize_telemetry_batch(
            payloads, source_id="test-gateway",
            expected_units={"load_kw": "kW"}, received_at=now,
        )


def test_batch_rejects_stale_and_bad_quality_data():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stale = _payloads(now)
    stale[0]["timestamp"] = (now - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="stale"):
        normalize_telemetry_batch(
            stale, source_id="test-gateway",
            expected_units={"load_kw": "kW", "battery_soc": "%"}, received_at=now,
        )
    bad = _payloads(now)
    bad[0]["quality"] = "bad"
    with pytest.raises(ValueError, match="quality"):
        normalize_telemetry_batch(
            bad, source_id="test-gateway",
            expected_units={"load_kw": "kW", "battery_soc": "%"}, received_at=now,
        )
