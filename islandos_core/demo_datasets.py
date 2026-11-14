"""Reproducible, clearly synthetic datasets for the public Streamlit demo."""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timedelta, timezone


FORECAST_HISTORY_COLUMNS = (
    "timestamp_utc",
    "pv_power_kw",
    "wind_power_kw",
    "essential_load_kw",
    "electricity_price_per_kwh",
)


def synthetic_forecast_history_csv(hours: int = 168) -> bytes:
    """Build a seven-day-by-default hourly CSV accepted by the forecast workflow."""
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 72:
        raise ValueError("hours must be an integer of at least 72")

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FORECAST_HISTORY_COLUMNS)
    writer.writeheader()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for index in range(hours):
        stamp = start + timedelta(hours=index)
        hour = stamp.hour
        solar = max(0.0, 32.0 * math.sin(math.pi * (hour - 6) / 12.0))
        pv = min(40.0, solar * (0.88 + 0.06 * math.sin(index * 0.19)))
        wind = min(20.0, 8.0 + 3.0 * math.sin(index * 0.23 + 0.8))
        load = 20.0 + 4.0 * (17 <= hour <= 22) + 2.0 * (7 <= hour <= 9)
        price = 0.08 if hour < 6 else 0.27 if 17 <= hour <= 21 else 0.16

        writer.writerow({
            "timestamp_utc": stamp.isoformat(timespec="minutes"),
            "pv_power_kw": round(max(0.0, pv), 4),
            "wind_power_kw": round(max(0.0, wind), 4),
            "essential_load_kw": round(load, 4),
            "electricity_price_per_kwh": round(price, 4),
        })

    return output.getvalue().encode("utf-8")
