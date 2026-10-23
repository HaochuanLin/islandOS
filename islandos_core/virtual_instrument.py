"""Deterministic virtual instrument helpers for development and contract tests."""
from __future__ import annotations

from datetime import datetime, timezone
import math

from .signals import SignalReading


def make_virtual_reading(signal_id: str, value: float, unit: str, *,
                         timestamp: datetime | None = None,
                         source: str = "virtual-instrument", quality: str = "good") -> SignalReading:
    """Create a validated virtual reading; never connects to physical equipment."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError("virtual instrument value must be finite")
    return SignalReading(signal_id=signal_id, value=numeric_value, unit=unit,
                         timestamp=timestamp, source=source, quality=quality)
