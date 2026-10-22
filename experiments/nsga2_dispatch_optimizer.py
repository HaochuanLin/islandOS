"""NSGA-II dispatch search for the islandOS energy-water screening model.

One integer gene per simulation interval selects an RO power level:
0=off, 1=6 kW, 2=8 kW, 3=10 kW.
Objectives (minimized): actual grid electricity cost and RO switch-on count.
Surplus renewable energy is an accounting metric only. Grid peak power is an
observation-only output. This is a model-based search, not a live controller.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.callback import Callback
from pymoo.core.crossover import Crossover
from pymoo.core.mutation import Mutation
from pymoo.core.problem import Problem
from pymoo.core.sampling import Sampling
from pymoo.optimize import minimize

from experiments.compare_energy_water_strategies import Config, SiteStep, _validate_config


POWER_LEVELS_KW = (0.0, 6.0, 8.0, 10.0)


def _decode_power_levels(chromosome: np.ndarray, step_count: int) -> list[float]:
    """Decode one categorical gene per interval into off / 6 / 8 / 10 kW."""
    genes = np.asarray(chromosome, dtype=int).reshape(-1)
    if len(genes) != step_count:
        raise ValueError("Chromosome length must match the number of input time steps.")
    if np.any(genes < 0) or np.any(genes >= len(POWER_LEVELS_KW)):
        raise ValueError("Each gene must be a power-level index in [0, 3].")
    return [POWER_LEVELS_KW[int(gene)] for gene in genes]


class DiscreteRandomSampling(Sampling):
    """Uniformly sample categorical power-level indices 0..3."""

    def _do(self, problem, n_samples, **kwargs):
        return np.random.randint(0, len(POWER_LEVELS_KW), size=(n_samples, problem.n_var))


class SinglePointDiscreteCrossover(Crossover):
    """Single-point crossover for integer categorical genes."""

    def __init__(self, prob: float = 0.9):
        super().__init__(2, 2, prob=prob)

    def _do(self, problem, X, **kwargs):
        # X shape: (n_parents, n_matings, n_var)
        children = X.copy()
        n_var = X.shape[2]
        if n_var < 2:
            return children
        for mating in range(X.shape[1]):
            point = np.random.randint(1, n_var)
            children[0, mating, point:] = X[1, mating, point:]
            children[1, mating, point:] = X[0, mating, point:]
        return children


class DiscreteLevelMutation(Mutation):
    """Per-gene mutation with pmut=1/n_var; mutated genes select another level."""

    def __init__(self, gene_mutation_probability: float):
        super().__init__(prob=1.0)
        self.gene_mutation_probability = gene_mutation_probability

    def _do(self, problem, X, **kwargs):
        mutated = X.copy().astype(int)
        mask = np.random.random(mutated.shape) < self.gene_mutation_probability
        for row, col in zip(*np.where(mask)):
            current = int(mutated[row, col])
            choices = [level for level in range(len(POWER_LEVELS_KW)) if level != current]
            mutated[row, col] = np.random.choice(choices)
        return mutated


def _evaluate_schedule(chromosome: np.ndarray, steps: list[SiteStep], config: Config):
    """Simulate the chromosome itself and return metrics and timestep audit."""
    requested_power_levels = _decode_power_levels(chromosome, len(steps))

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
        requested_power = requested_power_levels[i]
        source = None
        actual_power = 0.0
        if requested_power > 0 and inventory < config.tank_capacity_m3:
            if step.renewable_surplus_kw >= requested_power:
                source = "surplus"
                actual_power = requested_power
            elif step.grid_available and step.off_peak:
                source = "grid"
                actual_power = requested_power

        # A run ending before min_steps, including source interruption, is infeasible.
        if source is not None:
            run_length += 1
        else:
            if 0 < run_length < min_steps:
                min_run_violations += 1
            run_length = 0

        power = actual_power
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
            # Observation only: intentionally excluded from _objective_vector.
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
            "requested_ro_power_kw": requested_power,
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


def _objective_vector(summary: dict) -> tuple[float, float]:
    """The only two minimized objectives: actual grid cost and RO starts."""
    return (
        float(summary["grid_energy_cost"]),
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
    population_size: int = 120,
    generations: int = 60,
    seed: int = 42,
) -> tuple[list[dict], list[dict], dict]:
    """Return unique, feasible first-front schedules and metadata."""
    _validate_config(config)
    if not steps:
        raise ValueError("NSGA-II needs at least one input time step.")
    if population_size < 120 or generations < 60:
        raise ValueError("population_size must be >= 120 and generations must be >= 60.")
    n_var = len(steps)
    pmut = 1.0 / n_var

    class DispatchProblem(Problem):
        def __init__(self):
            # F: grid cost and RO starts. G <= 0 is feasible in pymoo.
            # Constraints cover unmet demand, min-run violations, and tank spill.
            super().__init__(n_var=n_var, n_obj=2, n_ieq_constr=3, xl=0, xu=3, vtype=int)

        def _evaluate(self, X, out, *args, **kwargs):
            objectives, constraints = [], []
            for chromosome in X:
                summary, _ = _evaluate_schedule(chromosome, steps, config)
                objectives.append(_objective_vector(summary))
                constraints.append([
                    summary["unmet_water_demand_m3"],
                    float(summary["minimum_run_constraint_violations"]),
                    summary["water_spill_m3"],
                ])
            out["F"] = np.asarray(objectives, dtype=float)
            out["G"] = np.asarray(constraints, dtype=float)

    # Archive each generation: result.X contains only the final population.
    class PopulationArchive(Callback):
        def __init__(self):
            super().__init__()
            self.chromosomes: list[np.ndarray] = []

        def notify(self, algorithm):
            population = algorithm.pop
            if population is not None and len(population):
                self.chromosomes.extend(
                    np.asarray(population.get("X"), dtype=int).copy()
                )

    archive = PopulationArchive()

    # NSGA-II: tournament selection is the algorithm's default selection.
    # Categorical integer genes use single-point crossover and per-gene mutation.
    algorithm = NSGA2(
        pop_size=int(population_size),
        sampling=DiscreteRandomSampling(),
        crossover=SinglePointDiscreteCrossover(prob=0.9),
        mutation=DiscreteLevelMutation(gene_mutation_probability=pmut),
        eliminate_duplicates=True,
    )
    result = minimize(
        DispatchProblem(), algorithm, ("n_gen", int(generations)),
        seed=int(seed), verbose=False, save_history=False, callback=archive,
    )
    if result.X is None and not archive.chromosomes:
        return [], [], {
            "feasible_count": 0,
            "unique_feasible_count": 0,
            "evaluations": int(getattr(result, "n_eval", 0) or 0),
            "population_size": int(population_size),
            "generations": int(generations),
            "pcross": 0.9,
            "pmut": pmut,
            "objective_count": 2,
            "message": "No feasible schedule found. Review demand, tank capacity, power availability, and minimum run duration.",
        }

    # Re-evaluate the returned population, reject infeasible schedules, and
    # explicitly filter the first non-dominated layer before CSV export.
    candidates: list[tuple[tuple[int, ...], dict, list[dict], tuple[float, ...]]] = []
    seen_genes: set[tuple[int, ...]] = set()
    # Include feasible candidates found in earlier generations, not only result.X.
    raw_candidates = list(archive.chromosomes)
    raw_candidates.extend(np.asarray(result.X, dtype=int) if result.X is not None else [])
    for raw_chromosome in raw_candidates:
        chromosome = np.asarray(raw_chromosome, dtype=int).reshape(-1)
        key = tuple(int(v) for v in chromosome)
        if key in seen_genes:
            continue
        seen_genes.add(key)
        summary, detail = _evaluate_schedule(chromosome, steps, config)
        tolerance = 1e-6
        if (
            summary["unmet_water_demand_m3"] > tolerance
            or summary["minimum_run_constraint_violations"] != 0
            or summary["water_spill_m3"] > tolerance
            or summary["ending_water_inventory_m3"] < -tolerance
            or summary["ending_water_inventory_m3"] > config.tank_capacity_m3 + tolerance
        ):
            continue
        candidates.append((key, summary, detail, _objective_vector(summary)))

    objective_vectors = [candidate[3] for candidate in candidates]
    first_front = [
        candidate for candidate in candidates
        if not _is_dominated(candidate[3], objective_vectors)
    ]
    # Keep unique schedules, not merely unique objective vectors. Distinct
    # schedules can have the same cost and switch count; collapsing by objectives
    # can incorrectly leave only one candidate row.
    first_front = sorted(first_front, key=lambda candidate: (candidate[3], candidate[0]))

    summaries: list[dict] = []
    schedules: list[dict] = []
    for _, summary, detail, _ in first_front:
        summary["strategy"] = f"nsga2_candidate_{len(summaries) + 1:02d}"
        summaries.append(summary)
        schedules.extend({**row, "strategy": summary["strategy"]} for row in detail)

    metadata = {
        "feasible_count": len(summaries),
        "unique_feasible_count": len(candidates),
        "distinct_objective_vectors": len(set(candidate[3] for candidate in candidates)),
        "evaluations": int(getattr(result, "n_eval", 0) or 0),
        "population_size": int(population_size),
        "generations": int(generations),
        "pcross": 0.9,
        "pmut": pmut,
        "gene_count": n_var,
        "objective_count": 2,
        "archived_population_candidates": len(archive.chromosomes),
        "message": (
            "NSGA-II first front only: unique feasible schedules minimizing actual "
            "grid cost and RO start count. Candidates are archived across generations; "
            "distinct schedules are retained even when objective values match. "
            "Surplus energy and grid peak are output metrics only; hard constraints "
            "require zero unmet demand, zero short-run violations, zero tank spill, "
            "and tank inventory within bounds (1e-6 numerical tolerance)."
        ),
    }
    return summaries, schedules, metadata
