"""Deterministic mock telemetry source for interface development only."""
from __future__ import annotations

from datetime import datetime, timezone


def make_mock_message(signal_id: str, value: float, unit: str, *,
                      site_id: str = "site-demo",
                      device_id: str = "mock-device-01",
                      observed_at: str | None = None) -> dict:
    """Create an explicitly labelled mock message; never represents real readings."""
    return {
        "schema_version": "0.1",
        "site_id": site_id,
        "device_id": device_id,
        "signal_id": signal_id,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "value": value,
        "unit": unit,
        "quality": "good",
        "source_type": "synthetic",
        "raw_reference": "mock-source:generated-for-interface-test",
    }
