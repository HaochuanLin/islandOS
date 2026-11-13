"""Bridge validated onboarding CSV data into the generic prediction engine.

This adapter is intentionally strict: it uses only confirmed canonical mappings,
requires explicit source units, preserves negative electricity tariffs, and never
fills missing values or changes the source series.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Any, Mapping

from .prediction_engine import ForecastRequest, SignalObservation


SIGNAL_UNITS = {
    "load_kw": "kW",
    "pv_power_kw": "kW",
    "wind_power_kw": "kW",
    "grid_import_kw": "kW",
    "grid_export_kw": "kW",
    "battery_charge_kw": "kW",
    "battery_discharge_kw": "kW",
    "battery_soc_pct": "%",
    "tariff_per_kwh": "currency/kWh",
    "diesel_power_kw": "kW",
    "diesel_fuel_lph": "L/h",
    "temperature_c": "degC",
}
SIGNED_SIGNALS = {"tariff_per_kwh", "temperature_c"}


def build_forecast_request(
    content: bytes,
    report: Mapping[str, Any],
    *,
    signal_id: str,
    horizon: int = 24,
) -> ForecastRequest:
    """Build a regular, timezone-aware forecast request from an inspected CSV."""
    if not isinstance(content, bytes) or not content:
        raise ValueError("CSV content must be non-empty bytes")
    if report.get("status") == "invalid" or report.get("error_count", 0):
        raise ValueError("onboarding report contains blocking import errors")
    if report.get("data_was_modified") is not False:
        raise ValueError("adapter requires an unmodified onboarding report")
    if signal_id not in SIGNAL_UNITS:
        raise ValueError(f"unsupported forecast signal: {signal_id}")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer")

    mappings = [item for item in report.get("column_mappings", [])
                if item.get("canonical_field") == signal_id]
    if len(mappings) != 1:
        raise ValueError(f"exactly one mapping for {signal_id} is required")
    mapping = mappings[0]
    if mapping.get("detected_source_unit") is None:
        raise ValueError(f"source unit for {signal_id} must be explicit")
    expected_unit = SIGNAL_UNITS[signal_id]
    if mapping.get("canonical_unit") != expected_unit:
        raise ValueError(f"canonical unit mismatch for {signal_id}")
    factor = mapping.get("conversion_to_canonical")
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or factor <= 0:
        raise ValueError("mapping conversion factor must be a positive number")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or mapping.get("source_column") not in reader.fieldnames:
        raise ValueError("mapped source column is missing from CSV")
    timestamp_column = report.get("timestamp_column")
    if timestamp_column not in reader.fieldnames:
        raise ValueError("recognized timestamp column is missing from CSV")

    observations = []
    for row_number, row in enumerate(reader, start=2):
        raw_timestamp = (row.get(timestamp_column) or "").strip()
        raw_value = (row.get(mapping["source_column"]) or "").strip()
        if not raw_timestamp or not raw_value:
            raise ValueError(f"missing timestamp or target value at CSV row {row_number}")
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            value = float(raw_value) * float(factor)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid timestamp or numeric value at CSV row {row_number}") from exc
        observations.append(SignalObservation(timestamp, value))

    if len(observations) < 3:
        raise ValueError("at least three complete observations are required")
    cadence = observations[1].timestamp - observations[0].timestamp
    if cadence.total_seconds() <= 0 or any(
        right.timestamp - left.timestamp != cadence
        for left, right in zip(observations, observations[1:])
    ):
        raise ValueError("target series must have a strictly increasing regular cadence")
    future = tuple(observations[-1].timestamp + cadence * step for step in range(1, horizon + 1))
    return ForecastRequest(
        signal_id=signal_id,
        unit=expected_unit,
        history=tuple(observations),
        target_timestamps=future,
        non_negative=signal_id not in SIGNED_SIGNALS,
    )
