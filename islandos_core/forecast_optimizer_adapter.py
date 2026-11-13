"""Bridge Phase 2 forecasts into the shared multi-resource dispatch optimizer.

This adapter is deliberately the only integration seam: it validates the
Phase 2 ForecastBundle, maps its named/unit-labelled signals into the existing
physical model contract, and carries source/model provenance into the result.
It does not promote forecast bounds into robust scenarios or authorize control.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Mapping, Sequence

from islandos_core.forecast_contract import build_forecast_planning_input
from islandos_core.assets import AssetRecord, evaluate_asset_readiness
from islandos_core.asset_energy_adapter import (
    AssetEnergyAdapterError,
    build_energy_system_config_from_assets,
)
from islandos_core.electrical_topology import ElectricalTopology
from islandos_core.operational_state import (
    AssetOperationalState,
    evaluate_operational_readiness,
)
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
    optimize_battery_and_diesel_schedule,
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



def build_site_energy_configuration(
    assets: Sequence[AssetRecord],
    observations: Sequence[AssetOperationalState],
    *,
    as_of: datetime,
    operating_assumptions: Mapping[str, object] | None = None,
    topology: ElectricalTopology | None = None,
    max_state_age: timedelta = timedelta(minutes=15),
    dt_hours: float = 1.0,
) -> dict:
    """Create a dispatch config only after static and operational readiness pass.

    This is a fail-closed offline screening adapter. It requires confirmed
    installed asset parameters, hard constraints, fresh confirmed online state,
    and—when supplied—a structurally validated declared topology.
    """
    if not assets:
        raise AssetEnergyAdapterError("at least one site asset is required")
    static = [evaluate_asset_readiness(asset) for asset in assets]
    blocked = [
        item for item in static if item.get("can_screen") is not True
    ]
    if blocked:
        detail = "; ".join(
            f"{item['asset_id']}:{','.join(item['blockers'])}" for item in blocked
        )
        raise AssetEnergyAdapterError(
            "site assets are not ready for offline screening: " + detail
        )
    operational = evaluate_operational_readiness(
        assets,
        observations,
        as_of=as_of,
        max_age=max_state_age,
        topology=topology,
    )
    if operational.get("can_dispatch_screen") is not True:
        raise AssetEnergyAdapterError(
            "site operational readiness is blocked: "
            + ", ".join(operational.get("blockers", []))
        )
    config = build_energy_system_config_from_assets(
        assets,
        dt_hours=dt_hours,
        operating_assumptions=operating_assumptions,
    )
    return {
        "site_id": assets[0].site_id,
        "asset_ids": [asset.asset_id for asset in assets],
        "config": config,
        "static_asset_readiness": static,
        "operational_readiness": operational,
        "scope": (
            "offline asset-to-energy-model configuration; state readiness is a "
            "snapshot, not a future availability forecast or device authorization"
        ),
    }


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




def optimize_forecasted_resource_schedule(
    bundle: ForecastBundle,
    config: EnergySystemConfig,
    *,
    grid_available: Sequence[bool],
    diesel_available: Sequence[bool],
    price_unit: str,
    weights: OptimizationWeights = OptimizationWeights(),
    population_size: int = 16,
    generations: int = 8,
    seed: int = 20261113,
    max_unmet_load_kwh: float | None = None,
    max_critical_unmet_load_kwh: float | None = None,
    terminal_battery_soc_min: float | None = None,
) -> dict:
    """Run joint battery/diesel schedule search across forecast stress scenarios.

    This path requires explicit battery and diesel asset configurations and
    diesel availability. It uses the existing seeded evolutionary optimizer;
    it is a bounded heuristic, not a guaranteed global optimum or controller.
    """
    if config.battery is None or config.diesel is None:
        raise OptimizationError(
            "joint resource scheduling requires configured battery and diesel assets"
        )
    if diesel_available is None:
        raise OptimizationError("diesel_available must be explicitly supplied")
    coordinated = build_coordination_inputs(
        bundle,
        grid_available=grid_available,
        diesel_available=diesel_available,
        price_unit=price_unit,
    )
    scenarios = _build_stress_scenarios(coordinated)
    additional = {
        name: scenario for name, scenario in scenarios.items()
        if name != "forecast_central"
    }
    result = optimize_battery_and_diesel_schedule(
        coordinated.inputs,
        config,
        weights=weights,
        population_size=population_size,
        generations=generations,
        seed=seed,
        additional_scenarios=additional,
        max_unmet_load_kwh=max_unmet_load_kwh,
        max_critical_unmet_load_kwh=max_critical_unmet_load_kwh,
        terminal_battery_soc_min=terminal_battery_soc_min,
    )
    result["forecast_provenance"] = {
        "history_sha256": coordinated.history_sha256,
        "model_ids": dict(coordinated.model_ids),
        "target_timestamps_utc": [
            timestamp.isoformat() for timestamp in coordinated.timestamps_utc
        ],
        "price_unit": coordinated.price_unit,
    }
    result["forecast_scenario_scope"] = {
        "nominal_plus_stress_scenarios": ["forecast_central", *additional.keys()],
        "scenario_probabilities_assigned": False,
        "bounds_are_joint_confidence_intervals": False,
        "same_schedule_replayed_across_all_scenarios": True,
        "objective_aggregation": "worst_case_across_supplied_scenarios",
    }
    result["decision_scope"] = (
        "offline joint battery/diesel schedule search across deterministic forecast "
        "envelopes and grid outage stress; seeded heuristic, not a global optimum, "
        "not site validation, and not authorization to write to devices"
    )
    return result


def build_service_equivalent_economics(result: dict, *, tolerance: float = 1e-6) -> dict:
    """Compare the recommendation with a named reference only at equivalent service."""
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise ValueError("tolerance must be a finite non-negative number")
    if not float(tolerance) < float("inf"):
        raise ValueError("tolerance must be finite")
    recommended_policy = result["recommendation"]["policy"]
    by_policy = {row["policy"]: row for row in result["candidates"]}
    reference_policy = "grid_first"
    recommended = by_policy[recommended_policy]["summary"]
    reference = by_policy[reference_policy]["summary"]
    service_metrics = (
        "load_served_kwh",
        "unmet_load_kwh",
        "critical_unmet_load_kwh",
        "flexible_load_shed_kwh",
    )
    deltas = {
        key: round(float(recommended.get(key, 0.0)) - float(reference.get(key, 0.0)), 8)
        for key in service_metrics
    }
    equivalent = all(abs(value) <= tolerance for value in deltas.values())
    cost_components = (
        "estimated_energy_cost",
        "gross_energy_cost",
        "grid_energy_cost",
        "diesel_energy_cost",
        "diesel_fuel_cost",
        "battery_degradation_cost",
        "grid_demand_charge",
        "grid_export_revenue",
    )
    component_comparison = {
        key: {
            "reference": float(reference.get(key, 0.0)),
            "recommended": float(recommended.get(key, 0.0)),
            "difference_recommended_minus_reference": round(
                float(recommended.get(key, 0.0)) - float(reference.get(key, 0.0)), 8
            ),
        }
        for key in cost_components
    }
    reference_cost = float(reference["estimated_energy_cost"])
    recommended_cost = float(recommended["estimated_energy_cost"])
    cost_delta = round(reference_cost - recommended_cost, 8)
    return {
        "reference_policy": reference_policy,
        "reference_is_measured_site_operation": False,
        "recommended_policy": recommended_policy,
        "service_equivalent": equivalent,
        "service_tolerance": float(tolerance),
        "service_deltas_recommended_minus_reference": deltas,
        "cost_components": component_comparison,
        "cost_comparison_valid": equivalent,
        "estimated_cost_reduction": cost_delta if equivalent else None,
        "estimated_cost_reduction_percent": (
            round(cost_delta / abs(reference_cost) * 100.0, 4)
            if equivalent and abs(reference_cost) > tolerance else None
        ),
        "interpretation": (
            "A modeled cost difference is shown only because both policies "
            "deliver equivalent modeled service; this is not a measured customer saving."
            if equivalent else
            "Service differs between policies; no cost saving is claimed. "
            "Compare reliability and load shedding before any economic conclusion."
        ),
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
    result["customer_economics"] = build_service_equivalent_economics(result)
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
