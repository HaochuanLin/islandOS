"""NSGA-II dispatch search for the islandOS energy-water screening model.

Each chromosome contains one requested RO on/off decision per input interval.
Objectives (all minimized): grid cost, negative renewable-surplus energy used,
peak grid power, and RO start count. Feasibility requires zero unmet demand,
zero minimum-run violations, and zero tank overflow. This is a model-based
search, not a trained model or a real equipment controller.
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
    """Simulate the chromosome itself and return its metrics and timestep audit."""
    if len(bits) != len(steps):
        raise ValueError("Chromosome length must match the number of input time steps.")

    inventory = config.initial_water_m3
    produced_total = served_total = unmet_total = spill_total = 0.0
    grid_cost = grid_energy = surplus_energy = grid_peak_kw = 0.0
    run_hours = 0.0
    details: list[dict[str, Any]] = []
    actual_on: list[bool] = []
    min_run_violations = 0
    run_length = 0
    min_steps = max(1, math.ceil(config.min_run_hours / config.dt_hours))

    for i, step in enumerate(steps):
        requested = bool(bits[i])
        source = None
        if requested and inventory < config.tank_capacity_m3:
            if step.renewable_surplus_kw >= config.ro_rated_power_kw:
                source = "surplus"
            elif step.grid_available and step.off_peak:
                source = "grid"

        # A run that ends before min_steps is infeasible. Source unavailability
        # also interrupts a requested run and is counted as a violation.
        if source is not None:
            run_length += 1
        else:
            if 0 < run_length < min_steps:
                min_run_violations += 1
            run_length = 0

        power = config.ro_rated_power_kw if source else 0.0
        energy = power * config.dt_hours
        produced = energy / config.specific_energy_kwh_m3
        before = inventory
        raw_inventory = inventory + produced
        spill = max(0.0, raw_inventory - config.tank_capacity_m3)
        inventory = min(config.tank_capacity_m3, raw_inventory)
        served = min(inventory, step.water_demand_m3)
        inventory -= served
        unmet = max(0.0, step.water_demand_m3 - served)

        if source == "surplus":
            surplus_energy += energy
        elif source == "grid":
            grid_energy += energy
            grid_cost += energy * step.grid_price_per_kwh
            grid_peak_kw = max(grid_peak_kw, power)

        if source:
            run_hours += config.dt_hours
        actual_on.append(source is not None)
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

    if 0 < run_length < min_steps:
        min_run_violations += 1

    switch_on_count = sum(
        1 for i, on in enumerate(actual_on)
        if on and (i == 0 or not actual_on[i - 1])
    )
    summary = {
        "strategy": "nsga2_candidate",
        "ro_run_hours": round(run_hours, 6),
        "water_produced_m3": round(produced_total, 6),
        "water_served_m3": round(served_total, 6),
        "unmet_water_demand_m3": float(unmet_total),
        "water_spill_m3": round(spill_total, 6),
        "surplus_energy_to_ro_kwh": round(surplus_energy, 6),
        "grid_energy_to_ro_kwh": round(grid_energy, 6),
        "grid_energy_cost": round(grid_cost, 6),
        "grid_peak_power_kw": round(grid_peak_kw, 6),
        "ro_switch_on_count": int(switch_on_count),
        "ending_water_inventory_m3": round(inventory, 6),
        "minimum_run_constraint_violations": int(min_run_violations),
    }
    return summary, details


def _objective_vector(summary: dict) -> tuple[float, float, float, float]:
    """Pymoo minimizes all objectives, so surplus use is negated."""
    return (
        float(summary["grid_energy_cost"]),
        -float(summary["surplus_energy_to_ro_kwh"]),
        float(summary["grid_peak_power_kw"]),
        float(summary["ro_switch_on_count"]),
    )


def _is_dominated(candidate: tuple[float, ...], others: list[tuple[float, ...]]) -> bool:
    """Return True if another objective vector is no worse in every objective."""
    for other in others:
        if all(a <= b for a, b in zip(other, candidate)) and any(
            a < b for a, b in zip(other, candidate)
        ):
            return True
    return False


def optimize_dispatch(
    steps: list[SiteStep],
    config: Config,
    population_size: int = 64,
    generations: int = 80,
    seed: int = 42,
) -> tuple[list[dict], list[dict], dict]:
    """Return the explicitly filtered feasible non-dominated schedules and metadata."""
    _validate_config(config)
    if len(steps) < 2:
        raise ValueError("NSGA-II needs at least two input time steps.")
    if population_size < 2 or generations < 1:
        raise ValueError("population_size must be >= 2 and generations must be >= 1.")
    n = len(steps)

    class DispatchProblem(Problem):
        def __init__(self):
            # Hard constraints: no unmet demand, no short run, no tank overflow.
            super().__init__(n_var=n, n_obj=4, n_ieq_constr=3, xl=0, xu=1, vtype=bool)

        def _evaluate(self, X, out, *args, **kwargs):
            objectives, constraints = [], []
            for bits in X:
                summary, _ = _evaluate_schedule(bits, steps, config)
                objectives.append(_objective_vector(summary))
                constraints.append([
                    summary["unmet_water_demand_m3"],
                    float(summary["minimum_run_constraint_violations"]),
                    summary["water_spill_m3"],
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
            "unique_feasible_count": 0,
            "evaluations": int(getattr(result, "n_eval", 0) or 0),
            "objective_count": 4,
            "message": "No feasible schedule found. Increase search budget or review whether the demand can be served without tank overflow.",
        }

    # Recompute, enforce constraints, deduplicate chromosomes, and explicitly
    # filter dominance across all four objective dimensions before CSV export.
    candidates: list[tuple[tuple[int, ...], dict, list[dict], tuple[float, ...]]] = []
    seen_genes: set[tuple[int, ...]] = set()
    for raw_bits in np.atleast_2d(result.X):
        bits = np.asarray(raw_bits, dtype=int).reshape(-1)
        key = tuple(int(v) for v in bits)
        if key in seen_genes:
            continue
        seen_genes.add(key)
        summary, detail = _evaluate_schedule(bits, steps, config)
        if (
            summary["unmet_water_demand_m3"] != 0.0
            or summary["minimum_run_constraint_violations"] != 0
            or summary["water_spill_m3"] != 0.0
        ):
            continue
        candidates.append((key, summary, detail, _objective_vector(summary)))

    objective_vectors = [c[3] for c in candidates]
    pareto = [c for c in candidates if not _is_dominated(c[3], objective_vectors)]
    pareto.sort(key=lambda c: (c[3][0], c[3][1], c[3][2], c[3][3]))

    summaries: list[dict] = []
    schedules: list[dict] = []
    for _, summary, detail, _ in pareto:
        summary["strategy"] = f"nsga2_candidate_{len(summaries) + 1:02d}"
        summaries.append(summary)
        schedules.extend({**row, "strategy": summary["strategy"]} for row in detail)

    metadata = {
        "feasible_count": len(summaries),
        "unique_feasible_count": len(candidates),
        "distinct_objective_vectors": len(set(c[3] for c in candidates)),
        "evaluations": int(getattr(result, "n_eval", 0) or 0),
        "population_size": int(population_size),
        "generations": int(generations),
        "seed": int(seed),
        "objective_count": 4,
        "message": (
            "Four-objective NSGA-II completed. Returned rows are unique, feasible "
            "non-dominated candidates under zero unmet demand, zero minimum-run "
            "violations, and zero tank overflow."
        ),
    }
    return summaries, schedules, metadata
