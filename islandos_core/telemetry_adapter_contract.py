"""Versioned, read-only telemetry adapter contract for IslandOS.

Concrete adapters may read files, simulators, gateways, or vendor APIs and map
their payloads into this contract. No write/control method is defined here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from types import MappingProxyType
from typing import Mapping, Sequence

from .signals import SignalReading, SignalValidationError, validate_signal_payload


@dataclass(frozen=True)
class TelemetryBatch:
    schema_version: str
    source_id: str
    received_at_utc: datetime
    readings: tuple[SignalReading, ...]
    batch_sha256: str


def normalize_telemetry_batch(
    payloads: Sequence[Mapping],
    *,
    source_id: str,
    expected_units: Mapping[str, str],
    received_at: datetime,
    max_age_seconds: float = 300.0,
) -> TelemetryBatch:
    """Validate and normalize a complete telemetry batch; reject partial batches."""
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id is required")
    if not isinstance(payloads, Sequence) or isinstance(payloads, (str, bytes)) or not payloads:
        raise ValueError("payloads must be a non-empty sequence")
    if not isinstance(expected_units, Mapping) or not expected_units:
        raise ValueError("expected_units must be a non-empty mapping")
    if not isinstance(received_at, datetime) or received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    received_utc = received_at.astimezone(timezone.utc)

    readings: list[SignalReading] = []
    seen: set[tuple[str, datetime]] = set()
    for index, payload in enumerate(payloads):
        if not isinstance(payload, Mapping):
            raise ValueError(f"payload at index {index} must be a mapping")
        signal_id = payload.get("signal_id")
        if not isinstance(signal_id, str) or signal_id not in expected_units:
            raise ValueError(f"unknown signal_id at index {index}")
        normalized = dict(payload)
        normalized["source"] = source_id
        try:
            reading = validate_signal_payload(
                normalized,
                expected_unit=expected_units[signal_id],
                now=received_utc,
                max_age_seconds=max_age_seconds,
            )
        except SignalValidationError as exc:
            raise ValueError(f"invalid telemetry at index {index}: {exc}") from exc
        identity = (reading.signal_id, reading.timestamp.astimezone(timezone.utc))
        if identity in seen:
            raise ValueError(f"duplicate telemetry reading: {reading.signal_id}")
        seen.add(identity)
        readings.append(reading)

    if {reading.signal_id for reading in readings} != set(expected_units):
        missing = sorted(set(expected_units) - {reading.signal_id for reading in readings})
        raise ValueError("telemetry batch is incomplete; missing: " + ", ".join(missing))

    stable = [
        {
            "signal_id": item.signal_id,
            "value": item.value,
            "unit": item.unit,
            "timestamp_utc": item.timestamp.astimezone(timezone.utc).isoformat(),
            "source": item.source,
            "quality": item.quality,
        }
        for item in sorted(readings, key=lambda item: (item.signal_id, item.timestamp))
    ]
    encoded = json.dumps(
        {"schema_version": "1.0", "source_id": source_id, "readings": stable},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return TelemetryBatch(
        schema_version="1.0",
        source_id=source_id,
        received_at_utc=received_utc,
        readings=tuple(readings),
        batch_sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )
