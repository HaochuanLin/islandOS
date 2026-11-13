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
    OptimizationError,
    OptimizationWeights,
    _audit,
    forecast_results_to_energy_inputs,
    optimize_energy_system,
)
from islandos_core.energy_system import dispatch_energy_system


@dataclass(frozen=True)
class ForecastCoordinationInputs:
    """Validated physical inputs plus forecast provenance for one horizon."""

    inputs: EnergySystemInputs
    timestamps_utc: tuple[datetime, ...]
    model_ids: Mapping[str, str]
    history_sha256: str
    price_unit: str
    lower_bounds: Mapping[str, tuple[float, ...]]
    upper_bounds: Mapping[str, tuple[float, ...]]


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
        lower_bounds=MappingProxyType({
            name: tuple(values) for name, values in planning.lower_bounds.items()
        }),
        upper_bounds=MappingProxyType({
            name: tuple(values) for name, values in planning.upper_bounds.items()
        }),
    )


def _build_stress_scenarios(coordinated: ForecastCoordinationInputs) -> dict[str, EnergySystemInputs]:
    """Build transparent deterministic stress envelopes; they are not probabilities."""
    base = coordinated.inputs
    lower = coordinated.lower_bounds
    upper = coordinated.upper_bounds

    def make(*, conservative: bool, grid_outage: bool = False) -> EnergySystemInputs:
        choose = upper if conservative else lower
        pv = lower["pv_power"] if conservative else upper["pv_power"]
        wind = lower["wind_power"] if conservative else upper["wind_power"]
        load = choose["essential_load"]
        price = choose["electricity_price"]
        changes = {
            "pv_generation_kw": pv,
            "wind_generation_kw": wind,
            "load_kw": load,
            "grid_price_per_kwh": price,
        }
        if "flexible_load" in choose:
            changes["flexible_load_kw"] = choose["flexible_load"]
        if "critical_load" in choose:
            critical = choose["critical_load"]
            # Critical demand is a subset of base load, not additive demand.
            changes["critical_load_kw"] = tuple(
                min(value, base_load)
                for value, base_load in zip(critical, load)
            )
        if grid_outage:
            changes["grid_available"] = tuple(False for _ in base.grid_available)
        return replace(base, **changes)

    return {
        "forecast_central": base,
        "conservative_forecast_envelope": make(conservative=True),
        "grid_outage": replace(
            base, grid_available=tuple(False for _ in base.grid_available)
        ),
        "combined_supply_and_grid_stress": make(
            conservative=True, grid_outage=True
        ),
    }


def evaluate_forecast_stress_scenarios(
    coordinated: ForecastCoordinationInputs,
    config: EnergySystemConfig,
) -> dict:
    """Replay each unchanged policy across shared stress scenarios.

    Scenario bounds are deterministic envelopes from the forecast bundle,
    not calibrated joint confidence intervals or probabilistic scenarios.
    """
    scenarios = _build_stress_scenarios(coordinated)
    policy_results = {}
    for policy in ("battery_first", "grid_first"):
        scenario_results = {}
        for name, inputs in scenarios.items():
            dispatch = dispatch_energy_system(inputs, config, policy=policy)
            audit = _audit(dispatch)
            if not audit["passed"]:
                raise OptimizationError(
                    f"Stress scenario {name!r} failed physical audit for {policy}: "
                    + ", ".join(audit["errors"])
                )
            summary = dispatch["summary"]
            scenario_results[name] = {
                "audit": audit,
                "summary": {
                    key: float(summary[key])
                    for key in (
                        "critical_unmet_load_kwh",
                        "unmet_load_kwh",
                        "estimated_energy_cost",
                        "renewable_curtailed_kwh",
                        "battery_throughput_kwh",
                        "grid_import_kwh",
                        "diesel_generation_kwh",
                    )
                },
            }
        metrics = tuple(next(iter(scenario_results.values()))["summary"])
        worst_case = {
            metric: max(row["summary"][metric] for row in scenario_results.values())
            for metric in metrics
        }
        policy_results[policy] = {
            "scenario_results": scenario_results,
            "worst_case": worst_case,
            "all_scenarios_passed_physical_audit": True,
        }

    # Lexicographic service-first ranking: never trade additional critical or
    # total unmet demand for a cheaper bill. Cost then breaks service ties.
    def rank(item: tuple[str, dict]) -> tuple[float, ...]:
        _, result = item
        worst = result["worst_case"]
        return (
            worst["critical_unmet_load_kwh"],
            worst["unmet_load_kwh"],
            worst["estimated_energy_cost"],
            worst["renewable_curtailed_kwh"],
            worst["battery_throughput_kwh"],
        )

    recommended_policy, recommended = min(policy_results.items(), key=rank)
    return {
        "scenario_count": len(scenarios),
        "scenario_names": list(scenarios),
        "policy_results": policy_results,
        "recommendation": {
            "policy": recommended_policy,
            "worst_case": recommended["worst_case"],
            "ranking": [
                "minimum worst-case critical unmet energy",
                "minimum worst-case total unmet energy",
                "minimum worst-case estimated energy cost",
                "minimum worst-case renewable curtailment",
                "minimum worst-case battery throughput",
            ],
        },
        "method_scope": {
            "type": "deterministic_forecast_envelope_and_grid_outage_stress_replay",
            "same_policy_replayed_across_all_scenarios": True,
            "scenario_probabilities_assigned": False,
            "joint_confidence_coverage_claimed": False,
            "robust_global_optimization_claimed": False,
            "site_or_safety_validation": False,
        },
    }


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
    result["forecast_stress_evaluation"] = evaluate_forecast_stress_scenarios(
        coordinated, config
    )
    result["forecast_provenance"] = {
        "history_sha256": coordinated.history_sha256,
        "model_ids": dict(coordinated.model_ids),
        "target_timestamps_utc": [
            timestamp.isoformat() for timestamp in coordinated.timestamps_utc
        ],
        "price_unit": coordinated.price_unit,
        "uncertainty_bounds_used_by_point_optimizer": False,
        "uncertainty_bounds_used_by_stress_evaluation": True,
        "data_provenance": "Inherited from ForecastBundle; see its input adapter",
    }
    result["decision_scope"] = (
        "offline policy comparison plus deterministic forecast-envelope and grid-outage "
        "stress replay; not probabilistic robust optimization, site validation, a live "
        "controller, or authorization to write to devices"
    )
    return result
