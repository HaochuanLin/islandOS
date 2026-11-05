"""Common-physics evaluation of candidate flexible-load schedules.

Every schedule is simulated by the same integrated physical model. This module generates a small set of transparent rule-based candidates and
ranks them; it does not forecast inputs or claim global optimality.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Mapping, Sequence

import numpy as np

from .microgrid_model import MicrogridConfig, MicrogridInputs, MicrogridResult, simulate_microgrid


@dataclass(frozen=True)
class ScheduleEvaluation:
    schedule_id: str
    feasible: bool
    essential_unserved_kwh: float
    unmet_water_m3: float
    operating_cost: float
    emissions_kg: float
    renewable_curtailed_kwh: float
    water_produced_m3: float
    ro_electricity_kwh: float
    result: MicrogridResult

    def to_dict(self) -> dict[str, str | bool | float]:
        """Return compact, JSON-compatible metrics (excluding hourly arrays)."""
        return {
            "schedule_id": self.schedule_id,
            "feasible": self.feasible,
            "essential_unserved_kwh": self.essential_unserved_kwh,
            "unmet_water_m3": self.unmet_water_m3,
            "operating_cost": self.operating_cost,
            "emissions_kg": self.emissions_kg,
            "renewable_curtailed_kwh": self.renewable_curtailed_kwh,
            "water_produced_m3": self.water_produced_m3,
            "ro_electricity_kwh": self.ro_electricity_kwh,
        }


def evaluate_ro_schedule(
    schedule_id: str,
    ro_power_schedule_kw: Sequence[float],
    inputs: MicrogridInputs,
    config: MicrogridConfig,
    *,
    essential_unserved_tolerance_kwh: float = 1e-8,
    unmet_water_tolerance_m3: float = 1e-8,
) -> ScheduleEvaluation:
    """Evaluate one requested RO power schedule against shared system physics."""
    if not isinstance(schedule_id, str) or not schedule_id.strip():
        raise ValueError("schedule_id must be a non-empty string")
    for name, value in (
        ("essential_unserved_tolerance_kwh", essential_unserved_tolerance_kwh),
        ("unmet_water_tolerance_m3", unmet_water_tolerance_m3),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and >= 0")
    try:
        requested = np.asarray(ro_power_schedule_kw, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("RO schedule must be a numeric one-dimensional series") from exc
    if requested.ndim != 1 or requested.size == 0 or not np.all(np.isfinite(requested)) or np.any(requested < 0):
        raise ValueError("RO schedule must be non-empty, finite, one-dimensional and non-negative")
    if len(requested) != len(inputs.pv_power_kw):
        raise ValueError("RO schedule length must match the physical input horizon")

    scenario = replace(inputs, ro_requested_power_kw=requested)
    result = simulate_microgrid(scenario, config)
    summary = result.summary()
    essential_unserved = summary["essential_unserved_kwh"]
    unmet_water = summary["unmet_water_demand_m3"]
    feasible = (
        essential_unserved <= essential_unserved_tolerance_kwh
        and unmet_water <= unmet_water_tolerance_m3
    )
    return ScheduleEvaluation(
        schedule_id=schedule_id,
        feasible=feasible,
        essential_unserved_kwh=essential_unserved,
        unmet_water_m3=unmet_water,
        operating_cost=summary["operating_cost"],
        emissions_kg=summary["emissions_kg"],
        renewable_curtailed_kwh=summary["renewable_curtailed_kwh"],
        water_produced_m3=summary["water_produced_m3"],
        ro_electricity_kwh=summary["ro_electricity_kwh"],
        result=result,
    )


def rank_ro_schedules(
    schedules: Mapping[str, Sequence[float]],
    inputs: MicrogridInputs,
    config: MicrogridConfig,
) -> list[ScheduleEvaluation]:
    """Rank candidate schedules lexicographically with service constraints first.

    Feasible schedules always rank ahead of infeasible ones. Within each group,
    minimize essential unserved energy, unmet water, operating cost, emissions,
    then renewable curtailment. This is a transparent screening order, not a
    weighted multi-objective optimum.
    """
    if not schedules:
        raise ValueError("at least one candidate schedule is required")
    evaluations = [
        evaluate_ro_schedule(schedule_id, schedule, inputs, config)
        for schedule_id, schedule in schedules.items()
    ]
    return sorted(
        evaluations,
        key=lambda item: (
            not item.feasible,
            item.essential_unserved_kwh,
            item.unmet_water_m3,
            item.operating_cost,
            item.emissions_kg,
            item.renewable_curtailed_kwh,
            item.schedule_id,
        ),
    )



def generate_renewable_surplus_candidates(
    inputs: MicrogridInputs,
    config: MicrogridConfig,
) -> dict[str, np.ndarray]:
    """Generate transparent, deterministic RO request schedules from supplied inputs.

    These are rule-based screening candidates, not forecasts or an optimizer.
    The physical evaluator still clips service to actual renewable headroom,
    RO nameplate capacity, and water-tank headroom.
    """
    try:
        pv = np.asarray(inputs.pv_power_kw, dtype=float)
        wind = np.asarray(inputs.wind_power_kw, dtype=float)
        essential = np.asarray(inputs.essential_load_kw, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("PV, wind, and essential-load inputs must be numeric series") from exc
    if any(x.ndim != 1 or x.size == 0 or not np.all(np.isfinite(x)) or np.any(x < 0)
           for x in (pv, wind, essential)):
        raise ValueError("PV, wind, and essential-load inputs must be finite non-negative series")
    if not (len(pv) == len(wind) == len(essential)):
        raise ValueError("PV, wind, and essential-load horizons must match")
    rated_power = config.ro_rated_power_kw
    if (
        isinstance(rated_power, (bool, np.bool_))
        or not isinstance(rated_power, (int, float, np.integer, np.floating))
        or not math.isfinite(float(rated_power))
        or rated_power <= 0
    ):
        raise ValueError("RO rated power must be finite and > 0 to generate candidates")

    surplus = np.clip(pv + wind - essential, 0.0, float(rated_power))
    return {
        "no_ro": np.zeros(len(pv), dtype=float),
        "conservative_surplus_50pct": surplus * 0.5,
        "renewable_surplus_full": surplus,
    }


def screen_renewable_surplus_candidates(
    inputs: MicrogridInputs,
    config: MicrogridConfig,
) -> list[ScheduleEvaluation]:
    """Generate and rank simple surplus-following candidates on common physics."""
    candidates = generate_renewable_surplus_candidates(inputs, config)
    return rank_ro_schedules(candidates, inputs, config)



@dataclass(frozen=True)
class RobustnessEvaluation:
    """Worst-case summary across explicit deterministic stress scenarios."""

    schedule_id: str
    robust_feasible: bool
    scenarios_evaluated: int
    worst_essential_unserved_kwh: float
    worst_unmet_water_m3: float
    worst_operating_cost: float
    worst_emissions_kg: float
    scenario_results: Mapping[str, ScheduleEvaluation]

    def to_dict(self) -> dict[str, str | bool | int | float]:
        return {
            "schedule_id": self.schedule_id,
            "robust_feasible": self.robust_feasible,
            "scenarios_evaluated": self.scenarios_evaluated,
            "worst_essential_unserved_kwh": self.worst_essential_unserved_kwh,
            "worst_unmet_water_m3": self.worst_unmet_water_m3,
            "worst_operating_cost": self.worst_operating_cost,
            "worst_emissions_kg": self.worst_emissions_kg,
        }


def evaluate_schedule_robustness(
    schedules: Mapping[str, Sequence[float]],
    inputs: MicrogridInputs,
    config: MicrogridConfig,
    *,
    stress_scenarios: Mapping[str, Mapping[str, float]] | None = None,
) -> list[RobustnessEvaluation]:
    """Re-simulate each schedule under deterministic input stress multipliers.

    Multipliers apply to PV, wind, essential load and water demand. Defaults
    include nominal, low-renewable, high-demand and combined stress cases.
    This is sensitivity analysis, not probabilistic forecasting or optimization.
    """
    if not schedules:
        raise ValueError("at least one candidate schedule is required")
    scenarios = stress_scenarios or {
        "nominal": {},
        "low_renewables": {"pv": 0.8, "wind": 0.8},
        "high_demand": {"essential_load": 1.15, "water_demand": 1.15},
        "combined_stress": {
            "pv": 0.8, "wind": 0.8,
            "essential_load": 1.15, "water_demand": 1.15,
        },
    }
    if not scenarios:
        raise ValueError("at least one stress scenario is required")

    allowed = {"pv", "wind", "essential_load", "water_demand"}
    validated: dict[str, dict[str, float]] = {}
    for scenario_name, multipliers in scenarios.items():
        if not isinstance(scenario_name, str) or not scenario_name.strip():
            raise ValueError("stress scenario names must be non-empty strings")
        if not isinstance(multipliers, Mapping):
            raise ValueError("stress scenario multipliers must be mappings")
        unknown = set(multipliers) - allowed
        if unknown:
            raise ValueError(f"unsupported stress multiplier(s): {sorted(unknown)}")
        clean: dict[str, float] = {}
        for key, value in multipliers.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{scenario_name}.{key} must be finite and non-negative")
            clean[key] = float(value)
        validated[scenario_name] = clean

    base_series = {
        "pv": np.asarray(inputs.pv_power_kw, dtype=float),
        "wind": np.asarray(inputs.wind_power_kw, dtype=float),
        "essential_load": np.asarray(inputs.essential_load_kw, dtype=float),
        "water_demand": np.asarray(inputs.water_demand_m3, dtype=float),
    }
    all_results: list[RobustnessEvaluation] = []
    for schedule_id, schedule in schedules.items():
        per_scenario: dict[str, ScheduleEvaluation] = {}
        for scenario_name, factors in validated.items():
            stressed_inputs = replace(
                inputs,
                pv_power_kw=base_series["pv"] * factors.get("pv", 1.0),
                wind_power_kw=base_series["wind"] * factors.get("wind", 1.0),
                essential_load_kw=base_series["essential_load"] * factors.get("essential_load", 1.0),
                water_demand_m3=base_series["water_demand"] * factors.get("water_demand", 1.0),
            )
            per_scenario[scenario_name] = evaluate_ro_schedule(
                schedule_id, schedule, stressed_inputs, config
            )
        values = list(per_scenario.values())
        all_results.append(RobustnessEvaluation(
            schedule_id=schedule_id,
            robust_feasible=all(item.feasible for item in values),
            scenarios_evaluated=len(values),
            worst_essential_unserved_kwh=max(item.essential_unserved_kwh for item in values),
            worst_unmet_water_m3=max(item.unmet_water_m3 for item in values),
            worst_operating_cost=max(item.operating_cost for item in values),
            worst_emissions_kg=max(item.emissions_kg for item in values),
            scenario_results=per_scenario,
        ))
    return sorted(
        all_results,
        key=lambda item: (
            not item.robust_feasible,
            item.worst_essential_unserved_kwh,
            item.worst_unmet_water_m3,
            item.worst_operating_cost,
            item.worst_emissions_kg,
            item.schedule_id,
        ),
    )
