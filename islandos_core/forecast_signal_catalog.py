"""Canonical signal vocabulary and site-level forecasting entry point.

This registry is the shared semantic layer between onboarding and forecasting.
It standardizes known signal identifiers, units, domains, and physical sign
constraints while keeping the underlying forecasting engine model-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Mapping, Sequence

from .forecast_engine import ForecastBundle, forecast_signals


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


def forecast_site_signals(
    timestamps: Sequence[datetime],
    history: Mapping[str, Sequence[float]],
    units: Mapping[str, str],
    horizon: int,
) -> ForecastBundle:
    """Forecast aligned site signals through one model-selection pipeline.

    Known IslandOS signals receive canonical unit and sign validation. Custom
    signals remain supported when callers provide an explicit unit; their sign
    is not constrained unless a future typed specification is registered.
    Every signal is evaluated independently against the same transparent
    baselines and chronological model-selection gate.
    """
    if not isinstance(history, Mapping) or not history:
        raise ValueError("history must be a non-empty mapping of site signals")
    if not isinstance(units, Mapping) or set(history) != set(units):
        raise ValueError("history and units must contain exactly the same signal names")

    non_negative: list[str] = []
    for signal_id in history:
        if not isinstance(signal_id, str) or not signal_id.strip():
            raise ValueError("signal identifiers must be non-empty strings")
        spec = get_forecast_signal_spec(signal_id)
        unit = units[signal_id]
        if spec is not None:
            _validate_unit(signal_id, unit, spec)
            if spec.non_negative:
                non_negative.append(signal_id)
        elif not isinstance(unit, str) or not unit.strip():
            raise ValueError(f"custom signal {signal_id} requires an explicit unit")

    return forecast_signals(
        timestamps,
        history,
        units,
        horizon,
        non_negative_signals=non_negative,
    )
