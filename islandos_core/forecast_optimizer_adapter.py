"""Bridge Phase 2 forecasts into the shared multi-resource dispatch optimizer.

This adapter is deliberately the only integration seam: it validates the
Phase 2 ForecastBundle, maps its named/unit-labelled signals into the existing
physical model contract, and carries source/model provenance into the result.
It does not promote forecast bounds into robust scenarios or authorize control.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Sequence

from islandos_core.forecast_contract import build_forecast_planning_input
from islandos_core.forecast_engine import ForecastBundle
from islandos_core.energy_system import EnergySystemConfig, EnergySystemInputs
from islandos_core.multisignal_forecasting import (
    SignalForecastPoint,
    SignalForecastResult,
)
from optimization.energy_system_optimizer import (
    OptimizationWeights,
    forecast_results_to_energy_inputs,
    optimize_energy_system,
)


@dataclass(frozen=True)
class ForecastCoordinationInputs:
    """Validated physical inputs plus forecast provenance for one horizon."""

    inputs: EnergySystemInputs
    timestamps_utc: tuple[datetime, ...]
    model_ids: Mapping[str, str]
    history_sha256: str
    price_unit: str


def build_coordination_inputs(
    bundle: ForecastBundle,
    *,
    grid_available: Sequence[bool],
    price_unit: str,
    diesel_available: Sequence[bool] | None = None,
    grid_export_price_per_kwh: Sequence[float] | None = None,
    grid_export_available: Sequence[bool] | None = None,
) -> ForecastCoordinationInputs:
    """Convert four Phase 2 forecasts to the physical dispatch input contract.

    Required bundle signal names and units:
      pv_power: kW
      wind_power: kW
      essential_load: kW
      electricity_price: exactly the caller-declared price_unit

    No unit conversion is attempted. The grid price may be negative. All four
    signals must share the same contiguous UTC hourly horizon. The physical
    optimizer consumes point predictions; uncertainty bounds remain available
    in the source ForecastBundle but are not yet used for robust optimization.
    """
    if not isinstance(price_unit, str) or not price_unit.strip():
        raise ValueError("price_unit must be a non-empty explicit unit such as USD/kWh")
    required_units = {
        "pv_power": "kW",
        "wind_power": "kW",
        "essential_load": "kW",
        "electricity_price": price_unit,
    }
    # Flexible demand is additive to essential/base demand. Critical demand is
    # an explicitly identified subset of the base demand.
    for optional_signal in ("flexible_load", "critical_load"):
        if optional_signal in bundle.forecasts:
            required_units[optional_signal] = "kW"
    planning = build_forecast_planning_input(bundle, required_units)

    def as_optimizer_forecast(source_name: str, target_id: str) -> SignalForecastResult:
        forecast = bundle.forecasts[source_name]
        points = tuple(
            SignalForecastPoint(
                timestamp=stamp,
                predicted_value=planning.values[source_name][index],
                lower_bound=planning.lower_bounds[source_name][index],
                upper_bound=planning.upper_bounds[source_name][index],
            )
            for index, stamp in enumerate(planning.timestamps)
        )
        return SignalForecastResult(
            signal_id=target_id,
            unit=planning.units[source_name],
            cadence_seconds=3600,
            model_id=forecast.model_id,
            model_version=forecast.model_version,
            input_history_sha256=planning.history_sha256,
            points=points,
        )

    pv = as_optimizer_forecast("pv_power", "pv_generation")
    wind = as_optimizer_forecast("wind_power", "wind_generation")
    load = as_optimizer_forecast("essential_load", "electrical_load")
    inputs, timestamps = forecast_results_to_energy_inputs(
        pv,
        wind,
        load,
        planning.values["electricity_price"],
        grid_available,
        diesel_available=diesel_available,
        grid_export_price_per_kwh=grid_export_price_per_kwh,
        grid_export_available=grid_export_available,
    )
    if tuple(timestamps) != planning.timestamps:
        raise ValueError("optimizer input timestamps differ from validated forecast horizon")

    optional_load_fields = {}
    if "flexible_load" in planning.values:
        optional_load_fields["flexible_load_kw"] = planning.values["flexible_load"]
    if "critical_load" in planning.values:
        critical = planning.values["critical_load"]
        base = planning.values["essential_load"]
        if any(value > base_value + 1e-9 for value, base_value in zip(critical, base)):
            raise ValueError("critical_load forecast cannot exceed essential_load forecast")
        optional_load_fields["critical_load_kw"] = critical
    if optional_load_fields:
        inputs = replace(inputs, **optional_load_fields)

    return ForecastCoordinationInputs(
        inputs=inputs,
        timestamps_utc=planning.timestamps,
        model_ids=MappingProxyType(dict(planning.model_ids)),
        history_sha256=planning.history_sha256,
        price_unit=price_unit,
    )


def optimize_forecasted_energy_system(
    bundle: ForecastBundle,
    config: EnergySystemConfig,
    *,
    grid_available: Sequence[bool],
    price_unit: str,
    weights: OptimizationWeights = OptimizationWeights(),
    diesel_available: Sequence[bool] | None = None,
    grid_export_price_per_kwh: Sequence[float] | None = None,
    grid_export_available: Sequence[bool] | None = None,
) -> dict:
    """Run the existing audited multi-resource policy optimizer on Phase 2 output.

    The return payload preserves source digest, selected model IDs, exact target
    timestamps, and the price unit. This is offline decision support only.
    """
    coordinated = build_coordination_inputs(
        bundle,
        grid_available=grid_available,
        price_unit=price_unit,
        diesel_available=diesel_available,
        grid_export_price_per_kwh=grid_export_price_per_kwh,
        grid_export_available=grid_export_available,
    )
    result = optimize_energy_system(coordinated.inputs, config, weights=weights)
    result["forecast_provenance"] = {
        "history_sha256": coordinated.history_sha256,
        "model_ids": dict(coordinated.model_ids),
        "target_timestamps_utc": [
            timestamp.isoformat() for timestamp in coordinated.timestamps_utc
        ],
        "price_unit": coordinated.price_unit,
        "uncertainty_bounds_used_by_optimizer": False,
        "data_provenance": "Inherited from ForecastBundle; see its input adapter",
    }
    result["decision_scope"] = (
        "offline policy comparison using point forecasts; not robust optimization, "
        "site validation, a live controller, or authorization to write to devices"
    )
    return result
