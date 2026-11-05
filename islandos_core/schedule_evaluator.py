"""Common-physics evaluation of candidate flexible-load schedules.

Every schedule is simulated by the same integrated physical model. This module
ranks supplied candidates; it does not generate schedules or claim optimality.
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
    pv = np.asarray(inputs.pv_power_kw, dtype=float)
    wind = np.asarray(inputs.wind_power_kw, dtype=float)
    essential = np.asarray(inputs.essential_load_kw, dtype=float)
    if any(x.ndim != 1 or x.size == 0 or not np.all(np.isfinite(x)) or np.any(x < 0)
           for x in (pv, wind, essential)):
        raise ValueError("PV, wind, and essential-load inputs must be finite non-negative series")
    if not (len(pv) == len(wind) == len(essential)):
        raise ValueError("PV, wind, and essential-load horizons must match")
    if config.ro_rated_power_kw <= 0:
        raise ValueError("RO rated power must be > 0 to generate candidates")

    surplus = np.clip(pv + wind - essential, 0.0, config.ro_rated_power_kw)
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
