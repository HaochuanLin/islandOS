"""Reconstruct historical RO operating cost from customer-exported interval data.

This is an accounting adapter, not a forecast or optimization claim. It refuses
missing/invalid fields and never fills gaps or invents site-specific prices.
"""
from __future__ import annotations

import csv
from datetime import datetime
import math
from pathlib import Path
from typing import TextIO

from ro_costing import ROCostRates, calculate_ro_operating_cost


REQUIRED_COLUMNS = (
    "timestamp",
    "energy_kwh",
    "water_produced_m3",
    "electricity_price_per_kwh",
    "runtime_hours",
    "start_events",
)


def _number(raw: str, column: str, row_number: int) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"row {row_number}: {column} must be numeric") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"row {row_number}: {column} must be finite and non-negative")
    return value


def reconstruct_historical_ro_cost(
    source: str | Path | TextIO,
    rates: ROCostRates,
    *,
    dt_hours: float,
    expected_interval_hours: float | None = None,
) -> dict:
    """Calculate actual-period cost from a CSV file or open text stream.

    Required columns are listed in REQUIRED_COLUMNS. Timestamps must be ISO-8601,
    unique and increasing. If expected_interval_hours is supplied, any gap or
    irregular interval is rejected rather than silently interpolated.
    """
    close_after = not hasattr(source, "read")
    handle = open(source, "r", encoding="utf-8-sig", newline="") if close_after else source
    try:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = [name for name in REQUIRED_COLUMNS if name not in fields]
        if missing:
            raise ValueError("missing required columns: " + ", ".join(missing))

        timestamps: list[datetime] = []
        energy: list[float] = []
        water: list[float] = []
        tariffs: list[float] = []
        runtime: list[float] = []
        starts: list[int] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                stamp = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
            except (AttributeError, ValueError) as exc:
                raise ValueError(f"row {row_number}: timestamp must be ISO-8601") from exc
            if timestamps and stamp <= timestamps[-1]:
                raise ValueError(f"row {row_number}: timestamps must be strictly increasing")
            timestamps.append(stamp)
            energy.append(_number(row["energy_kwh"], "energy_kwh", row_number))
            water.append(_number(row["water_produced_m3"], "water_produced_m3", row_number))
            tariffs.append(_number(row["electricity_price_per_kwh"], "electricity_price_per_kwh", row_number))
            runtime.append(_number(row["runtime_hours"], "runtime_hours", row_number))
            starts_value = _number(row["start_events"], "start_events", row_number)
            if not starts_value.is_integer():
                raise ValueError(f"row {row_number}: start_events must be an integer")
            starts.append(int(starts_value))

        if not timestamps:
            raise ValueError("CSV contains no data rows")
        if expected_interval_hours is not None:
            if not math.isfinite(expected_interval_hours) or expected_interval_hours <= 0:
                raise ValueError("expected_interval_hours must be > 0")
            for index in range(1, len(timestamps)):
                elapsed = (timestamps[index] - timestamps[index - 1]).total_seconds() / 3600
                if not math.isclose(elapsed, expected_interval_hours, rel_tol=0, abs_tol=1e-6):
                    raise ValueError(
                        f"timestamp gap/irregular interval between rows {index + 1} and {index + 2}; "
                        "no interpolation was performed"
                    )

        report = calculate_ro_operating_cost(
            energy, water, tariffs, rates,
            runtime_hours=runtime, start_events=starts,
            provenance="customer_uploaded_historical_data",
            dt_hours=dt_hours,
        )
        return {
            "status": "historical_cost_reconstructed",
            "data_provenance": "customer_uploaded_historical_data",
            "is_measured_site_data": True,
            "period_start": timestamps[0].isoformat(),
            "period_end": timestamps[-1].isoformat(),
            "rows": len(timestamps),
            "represented_hours": len(timestamps) * dt_hours,
            "timestamp_span_hours": (timestamps[-1] - timestamps[0]).total_seconds() / 3600,
            "interval_coverage_checked": expected_interval_hours is not None,
            "cost_report": report,
            "limitations": [
                "Only supplied cost components are included.",
                "Demand charges, taxes, backup fuel, renewable opportunity cost and water-quality penalties are excluded unless separately modelled.",
                "The report reconstructs the uploaded period; it does not annualize, forecast, or prove savings.",
            ],
        }
    finally:
        if close_after:
            handle.close()
