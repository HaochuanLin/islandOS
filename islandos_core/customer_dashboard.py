"""Customer-dashboard CSV adapter with strict cadence, units, and provenance checks."""
from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping


REQUIRED_CUSTOMER_COLUMNS = (
    "timestamp_utc",
    "pv_power_kw",
    "wind_power_kw",
    "essential_load_kw",
    "electricity_price_per_kwh",
)


@dataclass(frozen=True)
class CustomerHistory:
    timestamps_utc: tuple[datetime, ...]
    signals: Mapping[str, tuple[float, ...]]
    source_sha256: str
    row_count: int
    source_name: str = "user-uploaded CSV"


def parse_customer_history_csv(
    payload: bytes,
    *,
    min_rows: int = 72,
    source_name: str = "user-uploaded CSV",
) -> CustomerHistory:
    """Parse aligned hourly site history; never infer missing values or units."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("CSV upload must contain non-empty bytes")
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 72:
        raise ValueError("min_rows must be an integer of at least 72")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames
    if headers is None or len(headers) != len(set(headers)):
        raise ValueError("CSV must have one unique header for each required column")
    missing = [name for name in REQUIRED_CUSTOMER_COLUMNS if name not in headers]
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing))

    timestamps = []
    signals = {
        "pv_power": [],
        "wind_power": [],
        "essential_load": [],
        "electricity_price": [],
    }
    column_map = {
        "pv_power": "pv_power_kw",
        "wind_power": "wind_power_kw",
        "essential_load": "essential_load_kw",
        "electricity_price": "electricity_price_per_kwh",
    }
    for row_number, row in enumerate(reader, start=2):
        if None in row or any(row.get(name) is None for name in REQUIRED_CUSTOMER_COLUMNS):
            raise ValueError(f"row {row_number} has an invalid number of CSV fields")
        raw_stamp = (row.get("timestamp_utc") or "").strip()
        try:
            stamp = datetime.fromisoformat(raw_stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"row {row_number} has an invalid ISO-8601 timestamp") from exc
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError(f"row {row_number} timestamp must include a timezone")
        timestamps.append(stamp.astimezone(timezone.utc))

        for signal_name, column in column_map.items():
            raw_value = (row.get(column) or "").strip()
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ValueError(f"row {row_number} column {column} must be numeric") from exc
            if not math.isfinite(value):
                raise ValueError(f"row {row_number} column {column} must be finite")
            if signal_name != "electricity_price" and value < 0:
                raise ValueError(f"row {row_number} column {column} cannot be negative")
            signals[signal_name].append(value)

    if len(timestamps) < min_rows:
        raise ValueError(f"CSV requires at least {min_rows} hourly observations")
    for index, stamp in enumerate(timestamps):
        if index and stamp - timestamps[index - 1] != timedelta(hours=1):
            raise ValueError("timestamps must be strictly increasing contiguous hourly UTC instants")
    return CustomerHistory(
        timestamps_utc=tuple(timestamps),
        signals={name: tuple(values) for name, values in signals.items()},
        source_sha256=hashlib.sha256(payload).hexdigest(),
        row_count=len(timestamps),
        source_name=source_name,
    )
