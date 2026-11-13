"""Canonical signal vocabulary and pluggable site-level forecasting entry point.

The catalog is the semantic layer shared by data onboarding and prediction.
Known signals carry a domain, canonical unit, and physical sign constraint.
All signals are evaluated by the same model-agnostic PredictionEngine, whose
candidate registry supports chronological evaluation and model replacement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Mapping, Sequence

from .forecast_service import ForecastBundleRequest, ForecastService
from .prediction_engine import (
    ForecastRequest,
    PredictionEngine,
    PredictionResult,
    SignalObservation,
)


@dataclass(frozen=True)
class ForecastSignalSpec:
    signal_id: str
    domain: str
    canonical_unit: str
    non_negative: bool
    description: str


FORECAST_SIGNAL_SPECS: Mapping[str, ForecastSignalSpec] = {
    spec.signal_id: spec
    for spec in (
        ForecastSignalSpec("load_kw", "energy_demand", "kW", True, "Total site electrical load"),
        ForecastSignalSpec("flexible_load_kw", "energy_demand", "kW", True, "Shiftable or controllable electrical demand"),
        ForecastSignalSpec("critical_load_kw", "energy_demand", "kW", True, "Critical subset of base electrical demand"),
        ForecastSignalSpec("pv_power_kw", "energy_supply", "kW", True, "Solar photovoltaic output"),
        ForecastSignalSpec("wind_power_kw", "energy_supply", "kW", True, "Wind generation output"),
        ForecastSignalSpec("grid_import_kw", "energy_supply", "kW", True, "Grid import power"),
        ForecastSignalSpec("grid_export_kw", "energy_supply", "kW", True, "Grid export power"),
        ForecastSignalSpec("diesel_power_kw", "energy_supply", "kW", True, "Diesel generator electrical output"),
        ForecastSignalSpec("battery_charge_kw", "storage", "kW", True, "Battery charging power"),
        ForecastSignalSpec("battery_discharge_kw", "storage", "kW", True, "Battery discharging power"),
        ForecastSignalSpec("battery_soc_pct", "storage", "%", True, "Battery state of charge"),
        ForecastSignalSpec("tariff_per_kwh", "price", "currency/kWh", False, "Grid electricity tariff"),
        ForecastSignalSpec("diesel_fuel_lph", "fuel_demand", "L/h", True, "Diesel fuel consumption rate"),
        ForecastSignalSpec("water_demand_m3_per_hour", "resource_demand", "m3/h", True, "Hourly water demand"),
        ForecastSignalSpec("temperature_c", "environment", "degC", False, "Ambient temperature"),
    )
}

_CURRENCY_UNIT = re.compile(r"^[A-Z]{3}/kWh$")


@dataclass(frozen=True)
class SiteForecastBundle:
    input_history_sha256: str
    history_start_utc: datetime
    history_end_utc: datetime
    results: Mapping[str, PredictionResult]


def get_forecast_signal_spec(signal_id: str) -> ForecastSignalSpec | None:
    """Return the canonical specification for a known signal, if registered."""
    return FORECAST_SIGNAL_SPECS.get(signal_id)


def _validate_unit(signal_id: str, supplied: str, spec: ForecastSignalSpec) -> None:
    if not isinstance(supplied, str) or not supplied.strip():
        raise ValueError(f"{signal_id} requires an explicit non-empty unit")
    if spec.canonical_unit == "currency/kWh":
        if supplied != "currency/kWh" and not _CURRENCY_UNIT.fullmatch(supplied):
            raise ValueError(
                f"{signal_id} unit must be currency/kWh or an ISO currency unit such as USD/kWh"
            )
    elif supplied != spec.canonical_unit:
        raise ValueError(
            f"{signal_id} unit mismatch: expected {spec.canonical_unit}, got {supplied}"
        )


def _timestamps(values: Sequence[datetime]) -> tuple[datetime, ...]:
    stamps = tuple(values)
    if len(stamps) < 72:
        raise ValueError("At least 72 hourly timestamps are required")
    normalized = []
    for stamp in stamps:
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("All timestamps must be timezone-aware datetimes")
        normalized.append(stamp.astimezone(timezone.utc))
    for left, right in zip(normalized, normalized[1:]):
        if right - left != timedelta(hours=1):
            raise ValueError("Timestamps must be strictly ordered, contiguous hourly instants")
    return tuple(normalized)


def forecast_site_signals(
    timestamps: Sequence[datetime],
    history: Mapping[str, Sequence[float]],
    units: Mapping[str, str],
    horizon: int,
    *,
    engine: PredictionEngine | None = None,
    backtest_horizon: int = 24,
    season_length: int = 24,
    confidence_level: float = 0.90,
) -> SiteForecastBundle:
    """Forecast multiple site domains through one replaceable candidate engine.

    Known IslandOS signals receive canonical unit and sign validation. Custom
    signals remain supported when callers provide an explicit unit; their sign
    is not constrained unless a typed specification is registered. Candidate
    models are ranked by rolling-origin replay independently for each signal.
    """
    stamps = _timestamps(timestamps)
    if not isinstance(history, Mapping) or not history:
        raise ValueError("history must be a non-empty mapping of site signals")
    if not isinstance(units, Mapping) or set(history) != set(units):
        raise ValueError("history and units must contain exactly the same signal names")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 168:
        raise ValueError("horizon must be an integer from 1 to 168 hours")
    if isinstance(backtest_horizon, bool) or not isinstance(backtest_horizon, int) or backtest_horizon < 1:
        raise ValueError("backtest_horizon must be a positive integer")
    if isinstance(season_length, bool) or not isinstance(season_length, int) or season_length < 1:
        raise ValueError("season_length must be a positive integer")

    predictor = engine if engine is not None else PredictionEngine()
    if not isinstance(predictor, PredictionEngine):
        raise TypeError("engine must be a PredictionEngine instance")

    requests = []
    targets = tuple(
        stamps[-1] + timedelta(hours=offset)
        for offset in range(1, horizon + 1)
    )
    for signal_id in sorted(history):
        if not isinstance(signal_id, str) or not signal_id.strip():
            raise ValueError("signal identifiers must be non-empty strings")
        unit = units[signal_id]
        spec = get_forecast_signal_spec(signal_id)
        if spec is not None:
            _validate_unit(signal_id, unit, spec)
            non_negative = spec.non_negative
        else:
            if not isinstance(unit, str) or not unit.strip():
                raise ValueError(f"custom signal {signal_id} requires an explicit unit")
            non_negative = False

        values = list(history[signal_id])
        if len(values) != len(stamps):
            raise ValueError(f"{signal_id} must have one value for every timestamp")
        observations = tuple(
            SignalObservation(timestamp=stamp, value=value)
            for stamp, value in zip(stamps, values)
        )
        requests.append(ForecastRequest(
            signal_id=signal_id,
            unit=unit,
            history=observations,
            target_timestamps=targets,
            non_negative=non_negative,
        ))

    bundle = ForecastService(predictor).forecast_bundle(
        ForecastBundleRequest(tuple(requests)),
        backtest_horizon=backtest_horizon,
        season_length=season_length,
        confidence_level=confidence_level,
    )
    results = dict(bundle.forecasts)
    digest_payload = {
        signal_id: results[signal_id].input_history_sha256
        for signal_id in sorted(results)
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SiteForecastBundle(
        input_history_sha256=digest,
        history_start_utc=stamps[0],
        history_end_utc=stamps[-1],
        results=results,
    )
