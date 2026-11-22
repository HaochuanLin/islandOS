"""The call order behind the two decision pages, in one Streamlit-free place.

T4 gave a run a shape (``app_view_models``); this module gives it a *sequence*. The
dashboard page used to spell out forecast → coordination inputs → optimize → economics →
stress → paired impact inside its own body, and the joint optimizer page spelled out
manifest → dispatch search. A second front end would have had to reproduce that order
exactly, including which weights go where.

Nothing here calculates anything new: the functions call the same core entry points with
the same keyword arguments the pages used, and return every intermediate the pages still
read. No Streamlit import, no session state, no UI.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .energy_system import EnergySystemConfig
from .forecast_engine import forecast_signals
from .forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_service_equivalent_economics,
    evaluate_forecast_stress_scenarios,
)
from .impact_assessment import assess_energy_policy_impact
from optimization.energy_system_optimizer import optimize_energy_system, OptimizationWeights
from .planning_workflow import run_forecast_dispatch


def run_customer_dashboard(
    *,
    history_stamps: Sequence[Any],
    history: Mapping[str, Any],
    units: Mapping[str, str],
    site: Any,
    currency: str,
    cost_priority: float,
    provenance: str,
) -> dict:
    """The dashboard's run, in the order and with the weights the page has always used.

    ``site`` is a ``SiteAssumptions``; the config and the objective weights are derived
    here so the caller cannot pair a site with weights built from a different slider.
    """
    config: EnergySystemConfig = site.to_energy_system_config()
    bundle = forecast_signals(
        history_stamps,
        history,
        units,
        horizon=24,
        non_negative_signals=("pv_power", "wind_power", "essential_load"),
    )
    coordinated = build_coordination_inputs(
        bundle,
        grid_available=[True] * 24,
        price_unit=f"{currency}/kWh",
    )
    weights = OptimizationWeights(
        cost=float(cost_priority),
        reliability=float(1.0 - cost_priority),
        curtailment=0.0,
        battery_wear=0.0,
    )
    result = optimize_energy_system(coordinated.inputs, config, weights=weights)
    economics = build_service_equivalent_economics(result)
    stress = evaluate_forecast_stress_scenarios(coordinated, config)
    paired_impact = assess_energy_policy_impact(
        coordinated.inputs,
        config,
        currency=currency,
        evaluation_period="24-hour dispatch scenario",
        data_provenance=provenance,
    )
    return {
        "site": site,
        "config": config,
        "bundle": bundle,
        "coordinated": coordinated,
        "weights": weights,
        "result": result,
        "economics": economics,
        "stress": stress,
        "paired_impact": paired_impact,
    }


def run_joint_optimizer(
    *,
    run_manifest: Mapping[str, Any],
    timestamps: Sequence[Any],
    history: Mapping[str, Any],
    units: Mapping[str, str],
    config: EnergySystemConfig,
    grid_available: Sequence[bool],
    diesel_available: Sequence[bool],
) -> dict:
    """The joint optimizer's canonical run: dispatch search, then its own outputs.

    The forecast engine and the schedule search are one call here because the page has
    always obtained them through ``run_forecast_dispatch``; splitting them would invent a
    call order the core does not support.
    """
    planning_run = run_forecast_dispatch(
        run_manifest,
        timestamps=timestamps,
        history=history,
        units=units,
        energy_system_config=config,
        grid_available=list(grid_available),
        diesel_available=list(diesel_available),
    )
    predictions = planning_run["forecast_results"]
    target_timestamps = tuple(point.timestamp for point in predictions["pv_power_kw"].points)
    result = planning_run["optimization"]
    return {
        "planning_run": planning_run,
        "predictions": predictions,
        "target_timestamps": target_timestamps,
        "result": result,
        "handoff": result["generic_prediction_handoff"],
    }
