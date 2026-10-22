"""NSGA-II dispatch search for the islandOS synthetic/site-input screening model.

Decision variable: one binary RO on/off request per input interval. If on, the
source is selected deterministically: renewable surplus first (when it can
cover rated power), otherwise off-peak grid if available. The optimizer does
not invent data or control real equipment.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.operators.crossover.pntx import TwoPointCrossover
from pymoo.operators.mutation.bitflip import BitflipMutation
from pymoo.operators.sampling.rnd import BinaryRandomSampling
from pymoo.optimize import minimize

from experiments.compare_energy_water_strategies import Config, SiteStep, _validate_config


def _evaluate_schedule(bits: np.ndarray, steps: list[SiteStep], config: Config):
    inventory = config.initial_water_m3
    produced_total = served_total = unmet_total = spill_total = 0.0
    grid_cost = grid_energy = surplus_energy = 0.0
    run_hours = 0.0
    details: list[dict[str, Any]] = []
    run_length = 0
    min_run_violations = 0
    min_steps = max(1, math.ceil(config.min_run_hours / config.dt_hours))
    for i, step in enumerate(steps):
        requested = bool(bits[i])
        source = None
        if requested and inventory < config.tank_capacity_m3:
            if step.renewable_surplus_kw >= config.ro_rated_power_kw:
                source = "surplus"
            elif step.grid_available and step.off_peak:
                source = "grid"
        # An RO run cannot continue through an interval with no valid source.
        if source:
            run_length += 1
        elif run_length and run_length < min_steps:
            min_run_violations += 1
            run_length = 0
        else:
            run_length = 0

        power = config.ro_rated_power_kw if source else 0.0
        energy = power * config.dt_hours
        produced = energy / config.specific_energy_kwh_m3
        before = inventory
        inventory += produced
        spill = max(0.0, inventory - config.tank_capacity_m3)
        inventory = min(config.tank_capacity_m3, inventory)
        served = min(inventory, step.water_demand_m3)
        inventory -= served
        unmet = max(0.0, step.water_demand_m3 - served)
        if source == "surplus":
            surplus_energy += energy
        elif source == "grid":
            grid_energy += energy
            grid_cost += energy * step.grid_price_per_kwh
        run_hours += config.dt_hours if source else 0.0
        produced_total += produced
        served_total += served
        unmet_total += unmet
        spill_total += spill
        details.append({
            "timestamp": step.timestamp,
            "ro_source": source or "off",
            "ro_power_kw": round(power, 6),
            "ro_energy_kwh": round(energy, 6),
            "water_produced_m3": round(produced, 6),
            "water_inventory_before_m3": round(before, 6),
            "water_served_m3": round(served, 6),
            "unmet_water_demand_m3": round(unmet, 6),
            "water_spill_m3": round(spill, 6),
            "remaining_water_inventory_m3": round(inventory, 6),
            "grid_price_per_kwh": step.grid_price_per_kwh,
            "renewable_surplus_available_kw": step.renewable_surplus_kw,
        })
    if run_length and run_length < min_steps:
        min_run_violations += 1
    summary = {
        "strategy": "nsga2_candidate",
        "ro_run_hours": round(run_hours, 6),
        "water_produced_m3": round(produced_total, 6),
        "water_served_m3": round(served_total, 6),
        "unmet_water_demand_m3": round(unmet_total, 9),
        "water_spill_m3": round(spill_total, 6),
        "surplus_energy_to_ro_kwh": round(surplus_energy, 6),
        "grid_energy_to_ro_kwh": round(grid_energy, 6),
        "grid_energy_cost": round(grid_cost, 6),
        "ending_water_inventory_m3": round(inventory, 6),
        "minimum_run_constraint_violations": min_run_violations,
    }
    return summary, details


def optimize_dispatch(
    steps: list[SiteStep],
    config: Config,
    population_size: int = 64,
    generations: int = 80,
    seed: int = 42,
) -> tuple[list[dict], list[dict], dict]:
    """Return feasible non-dominated summary rows, corresponding schedules and run metadata."""
    _validate_config(config)
    if len(steps) < 2:
        raise ValueError("NSGA-II needs at least two input time steps.")
    n = len(steps)

    class DispatchProblem(Problem):
        def __init__(self):
            super().__init__(n_var=n, n_obj=2, n_ieq_constr=2, xl=0, xu=1, vtype=bool)

        def _evaluate(self, X, out, *args, **kwargs):
            objectives, constraints = [], []
            for bits in X:
                summary, _ = _evaluate_schedule(bits, steps, config)
                objectives.append([
                    summary["grid_energy_cost"],
                    -summary["surplus_energy_to_ro_kwh"],
                ])
                # Hard feasibility: unmet demand must be exactly zero; minimum run must hold.
                constraints.append([
                    summary["unmet_water_demand_m3"],
                    float(summary["minimum_run_constraint_violations"]),
                ])
            out["F"] = np.asarray(objectives, dtype=float)
            out["G"] = np.asarray(constraints, dtype=float)

    algorithm = NSGA2(
        pop_size=int(population_size),
        sampling=BinaryRandomSampling(),
        crossover=TwoPointCrossover(),
        mutation=BitflipMutation(prob=1.0 / n),
        eliminate_duplicates=True,
    )
    result = minimize(
        DispatchProblem(), algorithm, ("n_gen", int(generations)),
        seed=int(seed), verbose=False, save_history=False,
    )
    if result.X is None:
        return [], [], {
            "feasible_count": 0,
            "evaluations": int(getattr(result, "n_eval", 0) or 0),
            "message": "No feasible zero-unmet-demand schedule was found. Increase search budget or review input/model constraints.",
        }

    X = np.atleast_2d(result.X)
    summaries: list[dict] = []
    schedules: list[dict] = []
    seen: set[tuple[int, ...]] = set()
    for bits in X:
        summary, detail = _evaluate_schedule(bits, steps, config)
        if summary["unmet_water_demand_m3"] > 1e-8 or summary["minimum_run_constraint_violations"] != 0:
            continue
        key = tuple(int(v) for v in bits)
        if key in seen:
            continue
        seen.add(key)
        summary["strategy"] = f"nsga2_candidate_{len(summaries) + 1:02d}"
        summaries.append(summary)
        for row in detail:
            schedules.append({**row, "strategy": summary["strategy"]})
    summaries.sort(key=lambda r: (r["grid_energy_cost"], -r["surplus_energy_to_ro_kwh"]))
    metadata = {
        "feasible_count": len(summaries),
        "evaluations": int(getattr(result, "n_eval", 0) or 0),
        "population_size": int(population_size),
        "generations": int(generations),
        "seed": int(seed),
        "message": "NSGA-II search completed. Only zero-unmet-demand and minimum-run-feasible candidates are retained.",
    }
    return summaries, schedules, metadata
