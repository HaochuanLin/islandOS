"""Strict local-file adapter for the Open Power System Data hourly package.

The adapter reads only the selected region's columns from an OPSD
single-index CSV. It never downloads data, imputes missing values, resamples,
or silently bridges gaps. Returned timestamps are UTC-aware and suitable
for the generic IslandOS forecasting API.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence


OPSD_VERSION = "2020-10-06"
OPSD_SOURCE_URL = "https://data.open-power-system.org/time_series/2020-10-06/"
OPSD_ATTRIBUTION = (
    "Open Power System Data. 2020. Data Package Time series. "
    "Version 2020-10-06. https://doi.org/10.25832/time_series/2020-10-06. "
    "(Primary data from various sources; see OPSD source documentation.)"
)

_SIGNAL_COLUMNS = {
    "load": ("_load_actual_entsoe_transparency", "MW", True),
    "solar": ("_solar_generation_actual", "MW", True),
    "price": ("_price_day_ahead", "EUR/MWh", False),
}


@dataclass(frozen=True)
class PublicTimeSeriesDataset:
    """Aligned public observations plus explicit source provenance."""

    region_code: str
    timestamps: tuple[datetime, ...]
    history: Mapping[str, tuple[float, ...]]
    units: Mapping[str, str]
    source_columns: Mapping[str, str]
    source_name: str
    source_version: str
    source_url: str
    attribution: str
    data_sha256: str


def _parse_utc_timestamp(raw: str, line_number: int) -> datetime:
    value = raw.strip()
    if not value:
        raise ValueError(f"missing utc_timestamp at CSV line {line_number}")
    # OPSD documents the compact UTC format; accept ISO-8601 variants too.
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"invalid utc_timestamp at CSV line {line_number}: {value!r}"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"utc_timestamp must include a UTC offset at CSV line {line_number}")
        return parsed.astimezone(timezone.utc)


def _normalize_bound(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _resolve_columns(fieldnames: Sequence[str], region_code: str,
                     required_signals: Sequence[str]) -> dict[str, tuple[str, str, bool]]:
    available = set(fieldnames)
    resolved: dict[str, tuple[str, str, bool]] = {}
    for signal in required_signals:
        if signal == "wind":
            candidates = (
                f"{region_code}_wind_generation_actual",
                f"{region_code}_wind_onshore_generation_actual",
            )
            column = next((candidate for candidate in candidates if candidate in available), None)
            if column is None:
                raise ValueError(
                    f"OPSD CSV has no supported wind column for {region_code}; "
                    f"checked {', '.join(candidates)}"
                )
            resolved[signal] = (column, "MW", True)
            continue
        suffix, unit, non_negative = _SIGNAL_COLUMNS[signal]
        column = f"{region_code}{suffix}"
        if column not in available:
            raise ValueError(f"OPSD CSV is missing required column: {column}")
        resolved[signal] = (column, unit, non_negative)
    return resolved


def load_opsd_singleindex_csv(
    path: str | Path,
    region_code: str,
    *,
    required_signals: Sequence[str] = ("load", "solar", "wind", "price"),
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
) -> PublicTimeSeriesDataset:
    """Load a contiguous UTC slice from an OPSD 60-minute single-index CSV.

    The interval is [start_utc, end_utc). Missing/non-finite values in any
    required signal are errors rather than silently imputed or dropped.
    Wind uses the region's total wind column when available, otherwise its
    onshore generation column. Price is retained as signed EUR/MWh.
    """
    if not isinstance(region_code, str) or not re.fullmatch(r"[A-Z0-9_]+", region_code):
        raise ValueError("region_code must contain only uppercase letters, digits, and underscores")
    if isinstance(required_signals, (str, bytes)):
        raise ValueError("required_signals must be a non-empty sequence of signal names")
    signals = tuple(required_signals)
    if not signals or len(set(signals)) != len(signals):
        raise ValueError("required_signals must be non-empty and contain no duplicates")
    unknown = set(signals) - (set(_SIGNAL_COLUMNS) | {"wind"})
    if unknown:
        raise ValueError("unsupported OPSD signals: " + ", ".join(sorted(unknown)))

    start = _normalize_bound(start_utc, "start_utc")
    end = _normalize_bound(end_utc, "end_utc")
    if start is not None and end is not None and start >= end:
        raise ValueError("start_utc must be earlier than end_utc")

    csv_path = Path(path)
    timestamps: list[datetime] = []
    values: dict[str, list[float]] = {signal: [] for signal in signals}
    source_columns: dict[str, str] = {}
    units: dict[str, str] = {}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "utc_timestamp" not in reader.fieldnames:
            raise ValueError("OPSD CSV must contain a utc_timestamp column")
        resolved = _resolve_columns(reader.fieldnames, region_code, signals)
        source_columns = {signal: spec[0] for signal, spec in resolved.items()}
        units = {signal: spec[1] for signal, spec in resolved.items()}

        for line_number, row in enumerate(reader, start=2):
            stamp = _parse_utc_timestamp(row.get("utc_timestamp") or "", line_number)
            if start is not None and stamp < start:
                continue
            if end is not None and stamp >= end:
                continue

            parsed_values: dict[str, float] = {}
            for signal, (column, _unit, non_negative) in resolved.items():
                raw = (row.get(column) or "").strip()
                if not raw:
                    raise ValueError(
                        f"missing {signal} value in column {column} at CSV line {line_number}; "
                        "select a complete contiguous date range or omit that signal"
                    )
                try:
                    number = float(raw)
                except ValueError as exc:
                    raise ValueError(
                        f"non-numeric {signal} value in column {column} at CSV line {line_number}"
                    ) from exc
                if not math.isfinite(number):
                    raise ValueError(
                        f"non-finite {signal} value in column {column} at CSV line {line_number}"
                    )
                if non_negative and number < 0:
                    raise ValueError(
                        f"negative {signal} value in column {column} at CSV line {line_number}"
                    )
                parsed_values[signal] = number

            if timestamps and stamp - timestamps[-1] != timedelta(hours=1):
                raise ValueError(
                    "selected OPSD rows must be strictly ordered and contiguous hourly UTC instants"
                )
            timestamps.append(stamp)
            for signal, number in parsed_values.items():
                values[signal].append(number)

    if not timestamps:
        raise ValueError("no OPSD observations found for the requested region and time range")

    history = {signal: tuple(series) for signal, series in values.items()}
    digest_payload = {
        "source_version": OPSD_VERSION,
        "region_code": region_code,
        "timestamps_utc": [stamp.isoformat() for stamp in timestamps],
        "source_columns": source_columns,
        "units": units,
        "history": history,
    }
    canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return PublicTimeSeriesDataset(
        region_code=region_code,
        timestamps=tuple(timestamps),
        history=history,
        units=units,
        source_columns=source_columns,
        source_name="Open Power System Data",
        source_version=OPSD_VERSION,
        source_url=OPSD_SOURCE_URL,
        attribution=OPSD_ATTRIBUTION,
        data_sha256=digest,
    )
