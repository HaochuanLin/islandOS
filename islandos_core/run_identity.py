"""Canonical, currency-neutral input-group identity for IslandOS runs.

P1a deliberately stops at input identity. It does not derive run IDs, read
environment variables, touch Streamlit, or open a database. The same physical
history expressed through Page 05 and Page 06 field names must produce the same
``input_group_id``; a change to the physical unit grid must produce a different
one. Currency labels are canonicalised to ``currency/kWh`` so USD and CNY do
not split an otherwise identical input group.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from islandos_core.demo_site_history import canonical_history_sha256


INPUT_GROUP_SCHEMA = "islandos-input-group-v1"
INPUT_GROUP_SCHEMA_VERSION = 1
TARIFF_UNIT_TOKEN = "currency/kWh"

CANONICAL_SIGNAL_NAMES = (
    "pv_power_kw",
    "wind_power_kw",
    "load_kw",
    "tariff_per_kwh",
)
POWER_SIGNAL_NAMES = CANONICAL_SIGNAL_NAMES[:3]
PAGE_SIGNAL_ALIASES = {
    "pv_power": "pv_power_kw",
    "wind_power": "wind_power_kw",
    "essential_load": "load_kw",
    "electricity_price": "tariff_per_kwh",
}
_CURRENCY_UNIT = re.compile(r"^[A-Z]{3}/kWh$")


class RunIdentityError(ValueError):
    """Base error for invalid identity inputs; messages are deterministic."""


@dataclass(frozen=True)
class InputGroupIdentity:
    """A stable identity for the physical input series, independent of pages."""

    input_group_id: str
    input_group_sha256: str
    history_sha256: str
    units_sha256: str
    hour_count: int
    schema_version: int = INPUT_GROUP_SCHEMA_VERSION


def canonical_signal_name(name: str) -> str:
    """Map a Page 05 display name or canonical name to the physical name."""
    if not isinstance(name, str) or not name.strip():
        raise RunIdentityError("signal names must be non-empty strings")
    if name in CANONICAL_SIGNAL_NAMES:
        return name
    if name in PAGE_SIGNAL_ALIASES:
        return PAGE_SIGNAL_ALIASES[name]
    raise RunIdentityError(f"unsupported signal name: {name}")


def _canonical_mapping(mapping: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(mapping, Mapping):
        raise RunIdentityError(f"{field} must be a mapping")
    normalized: dict[str, Any] = {}
    for raw_name, value in mapping.items():
        name = canonical_signal_name(raw_name)
        if name in normalized:
            raise RunIdentityError(f"{field} contains duplicate signal: {name}")
        normalized[name] = value
    if set(normalized) != set(CANONICAL_SIGNAL_NAMES):
        raise RunIdentityError(
            f"{field} must contain exactly the four canonical signals"
        )
    return normalized


def canonicalize_history_signals(
    signals: Mapping[str, Sequence[float]],
) -> dict[str, list[float]]:
    """Return canonical physical names and validated numeric series.

    Both Page 05 (short display names) and Page 06 (physical names) are
    accepted. Missing, extra, or duplicate signals fail closed instead of
    being silently dropped or imputed.
    """
    normalized = _canonical_mapping(signals, "signals")
    lengths = set()
    result: dict[str, list[float]] = {}
    for name in CANONICAL_SIGNAL_NAMES:
        values = normalized[name]
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise RunIdentityError(f"signal {name} must be a sequence of numbers")
        if not values:
            raise RunIdentityError(f"signal {name} must not be empty")
        cleaned: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RunIdentityError(f"signal {name} must contain only finite numbers")
            number = float(value)
            if not math.isfinite(number):
                raise RunIdentityError(f"signal {name} must contain only finite numbers")
            cleaned.append(number)
        result[name] = cleaned
        lengths.add(len(cleaned))
    if len(lengths) != 1:
        raise RunIdentityError("all four signal arrays must share one length")
    return result


def canonicalize_units(units: Mapping[str, str]) -> dict[str, str]:
    """Return fixed physical unit labels with a currency-neutral tariff token."""
    normalized = _canonical_mapping(units, "units")
    result: dict[str, str] = {}
    for name in CANONICAL_SIGNAL_NAMES:
        unit = normalized[name]
        if not isinstance(unit, str) or not unit.strip():
            raise RunIdentityError(f"unit for {name} must be a non-empty string")
        unit = unit.strip()
        if name == "tariff_per_kwh" and _CURRENCY_UNIT.fullmatch(unit):
            unit = TARIFF_UNIT_TOKEN
        result[name] = unit
    return result


def _utc_timestamps(timestamps: Sequence[datetime]) -> tuple[datetime, ...]:
    if not isinstance(timestamps, Sequence) or isinstance(timestamps, (str, bytes)):
        raise RunIdentityError("timestamps must be a sequence of timezone-aware datetimes")
    if not timestamps:
        raise RunIdentityError("timestamps must not be empty")
    normalized: list[datetime] = []
    for value in timestamps:
        if not isinstance(value, datetime):
            raise RunIdentityError("timestamps must contain timezone-aware datetimes")
        if value.tzinfo is None or value.utcoffset() is None:
            raise RunIdentityError("timestamps must be timezone-aware")
        normalized.append(value.astimezone(timezone.utc))
    if len(set(normalized)) != len(normalized):
        raise RunIdentityError("timestamps must be unique")
    return tuple(sorted(normalized))


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def derive_input_group_id(
    *,
    timestamps: Sequence[datetime],
    signals: Mapping[str, Sequence[float]],
    units: Mapping[str, str],
) -> InputGroupIdentity:
    """Derive a cross-page identity from canonical history, units and row count.

    The time axis is sorted in UTC before hashing, so equivalent histories
    supplied in a different row order produce the same group. Duplicate
    timestamps are refused because their ordering would be ambiguous. Values
    are quantised to six decimals by ``canonical_history_sha256``; no null
    values are allowed and no missing rows are imputed.
    """
    stamps = _utc_timestamps(timestamps)
    normalized_signals = canonicalize_history_signals(signals)
    normalized_units = canonicalize_units(units)

    lengths = {len(values) for values in normalized_signals.values()}
    if len(lengths) != 1:
        raise RunIdentityError("all four signal arrays must share one length")
    hour_count = len(stamps)
    if next(iter(lengths)) != hour_count:
        raise RunIdentityError("timestamps and all four signal arrays must have the same length")

    # Sorting timestamps may require reordering the corresponding signal rows.
    source_stamps = [
        value.astimezone(timezone.utc) if isinstance(value, datetime) else value
        for value in timestamps
    ]
    order = sorted(range(hour_count), key=lambda index: source_stamps[index])
    sorted_signals = {
        name: [normalized_signals[name][index] for index in order]
        for name in CANONICAL_SIGNAL_NAMES
    }

    history_sha256 = canonical_history_sha256(
        timestamps=stamps,
        pv_power_kw=tuple(sorted_signals["pv_power_kw"]),
        wind_power_kw=tuple(sorted_signals["wind_power_kw"]),
        load_kw=tuple(sorted_signals["load_kw"]),
        tariff_per_kwh=tuple(sorted_signals["tariff_per_kwh"]),
    )
    units_sha256 = _sha256(normalized_units)
    input_group_sha256 = _sha256({
        "schema": INPUT_GROUP_SCHEMA,
        "history_sha256": history_sha256,
        "units_sha256": units_sha256,
        "hour_count": hour_count,
    })
    return InputGroupIdentity(
        input_group_id=f"ig-{input_group_sha256[:16]}",
        input_group_sha256=input_group_sha256,
        history_sha256=history_sha256,
        units_sha256=units_sha256,
        hour_count=hour_count,
    )
