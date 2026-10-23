"""Adapters from offline simulation rows to the normalized signal contract.

These readings are explicitly virtual/offline; this module does not read telemetry
or communicate with plant equipment.
"""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Mapping

from .signals import SignalReading
from .virtual_instrument import make_virtual_reading


class SimulationRowAdapterError(ValueError):
    """Raised when a simulation row cannot be mapped safely to signals."""


def simulation_row_to_screening_signals(
    row: Mapping[str, Any],
    *,
    timestamp_key: str = "timestamp",
    source: str = "offline-simulation",
) -> tuple[SignalReading, SignalReading]:
    """Map a simulation row to renewable-surplus and water-inventory readings.

    Required row keys are renewable_surplus_available_kw,
    water_inventory_before_m3, and a timezone-aware ISO-8601 timestamp.
    Values are mapped, not interpreted as live measurements.
    """
    required = (timestamp_key, "renewable_surplus_available_kw", "water_inventory_before_m3")
    missing = [key for key in required if key not in row]
    if missing:
        raise SimulationRowAdapterError("missing simulation row fields: " + ", ".join(missing))

    raw_timestamp = row[timestamp_key]
    if isinstance(raw_timestamp, datetime):
        timestamp = raw_timestamp
    elif isinstance(raw_timestamp, str):
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SimulationRowAdapterError("timestamp must be valid ISO-8601") from exc
    else:
        raise SimulationRowAdapterError("timestamp must be a datetime or ISO-8601 string")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise SimulationRowAdapterError("timestamp must include a timezone")

    def nonnegative_number(key: str) -> float:
        try:
            value = float(row[key])
        except (TypeError, ValueError) as exc:
            raise SimulationRowAdapterError(f"{key} must be numeric") from exc
        if not math.isfinite(value) or value < 0:
            raise SimulationRowAdapterError(f"{key} must be finite and >= 0")
        return value

    renewable = nonnegative_number("renewable_surplus_available_kw")
    inventory = nonnegative_number("water_inventory_before_m3")
    return (
        make_virtual_reading("renewable_surplus_kw", renewable, "kW", timestamp=timestamp, source=source),
        make_virtual_reading("water_inventory_m3", inventory, "m3", timestamp=timestamp, source=source),
    )
