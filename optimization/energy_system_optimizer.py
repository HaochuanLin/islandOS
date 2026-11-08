"""Forecast-connected multi-resource dispatch optimization baseline.

This first optimization layer searches the two auditable operating policies
implemented by the shared physical simulator. It is deliberately a bounded
policy optimizer, not a claim of global hourly set-point optimization.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Sequence

from islandos_core.energy_system import (
    EnergySystemConfig, EnergySystemInputs, dispatch_energy_system,
)
from islandos_core.multisignal_forecasting import SignalForecastResult


class OptimizationError(ValueError):
    """Raised when an optimization request is incomplete or inconsistent."""


@dataclass(frozen=True)
class OptimizationWeights:
    cost: float = 0.70
    reliability: float = 0.20
    curtailment: float = 0.10

    def __post_init__(self) -> None:
        values = (self.cost, self.reliability, self.curtailment)
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(float(v)) or v < 0 for v in values):
            raise OptimizationError("objective weights must be finite and non-negative")
        if sum(values) <= 0:
            raise OptimizationError("at least one objective weight must be positive")


def forecast_results_to_energy_inputs(
    pv: SignalForecastResult,
    wind: SignalForecastResult,
    load: SignalForecastResult,
    grid_price_per_kwh: Sequence[float],
    grid_available: Sequence[bool],
    *,
    diesel_available: Sequence[bool] | None = None,
    grid_export_price_per_kwh: Sequence[float] | None = None,
    grid_export_available: Sequence[bool] | None = None,
) -> tuple[EnergySystemInputs, tuple]:
    """Align three stage-3 forecasts into the physical engine's typed inputs."""
    forecasts = (("pv_generation", pv, "kW"),
                 ("wind_generation", wind, "kW"),
                 ("electrical_load", load, "kW"))
    reference = tuple(point.timestamp for point in pv.points)
    if not reference:
        raise OptimizationError("forecasts must contain at least one point")
    for signal_id, result, unit in forecasts:
        if result.signal_id != signal_id or result.unit != unit:
            raise OptimizationError(f"{signal_id} forecast must use signal_id={signal_id!r} and unit={unit!r}")
        if tuple(point.timestamp for point in result.points) != reference:
            raise OptimizationError("PV, wind, and load forecast timestamps must match exactly")
        if result.cadence_seconds != pv.cadence_seconds:
            raise OptimizationError("forecast cadences must match exactly")
    n = len(reference)
    numeric = {
        "grid_price_per_kwh": grid_price_per_kwh,
        "grid_available": grid_available,
    }
    for name, values in numeric.items():
        if isinstance(values, (str, bytes)) or len(values) != n:
            raise OptimizationError(f"{name} must contain exactly {n} values")
    for name, values in (("diesel_available", diesel_available),
                         ("grid_export_price_per_kwh", grid_export_price_per_kwh),
                         ("grid_export_available", grid_export_available)):
        if values is not None and (isinstance(values, (str, bytes)) or len(values) != n):
            raise OptimizationError(f"{name} must contain exactly {n} values")
    for name, values in (("grid_available", grid_available),
                         ("diesel_available", diesel_available),
                         ("grid_export_available", grid_export_available)):
        if values is not None and any(not isinstance(v, bool) for v in values):
            raise OptimizationError(f"{name} must contain boolean values")
    def values(result: SignalForecastResult) -> list[float]:
        return [float(point.predicted_value) for point in result.points]
    inputs = EnergySystemInputs(
        pv_generation_kw=values(pv),
        wind_generation_kw=values(wind),
        load_kw=values(load),
        grid_price_per_kwh=list(grid_price_per_kwh),
        grid_available=list(grid_available),
        diesel_available=list(diesel_available) if diesel_available is not None else None,
        grid_export_price_per_kwh=(
            list(grid_export_price_per_kwh) if grid_export_price_per_kwh is not None else None
        ),
        grid_export_available=(
            list(grid_export_available) if grid_export_available is not None else None
        ),
    )
    return inputs, reference


def _dominates(left: dict, right: dict) -> bool:
    keys = ("estimated_energy_cost", "unmet_load_kwh",
            "renewable_curtailed_kwh", "battery_throughput_kwh")
    a = [left["objectives"][key] for key in keys]
    b = [right["objectives"][key] for key in keys]
    return all(x <= y + 1e-9 for x, y in zip(a, b)) and any(
        x < y - 1e-9 for x, y in zip(a, b)
    )


def _audit(result: dict) -> dict:
    rows = result["rows"]
    errors = []
    for index, row in enumerate(rows):
        residual = row.get("energy_balance_residual_kw")
        if not isinstance(residual, (int, float)) or not math.isfinite(float(residual)):
            errors.append(f"invalid_energy_balance_residual_at_{index}")
        elif abs(float(residual)) > 1e-7:
            errors.append(f"energy_balance_failed_at_{index}")
        if row.get("unmet_load_kw", 0.0) < -1e-9:
            errors.append(f"negative_unmet_load_at_{index}")
        if row.get("battery_soc") is not None and not 0 <= row["battery_soc"] <= 1:
            errors.append(f"battery_soc_out_of_range_at_{index}")
    summary = result["summary"]
    required = ("estimated_energy_cost", "unmet_load_kwh",
                "renewable_curtailed_kwh", "battery_throughput_kwh")
    for key in required:
        value = summary.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errors.append(f"invalid_summary_{key}")
    return {"passed": not errors, "errors": errors,
            "scope": "independent audit of simulator energy-balance residuals and reported summary finiteness; not field or safety validation"}


def optimize_energy_system(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    weights: OptimizationWeights = OptimizationWeights(),
) -> dict:
    """Evaluate both physical dispatch policies and rank feasible Pareto choices.

    Every candidate receives identical forecasts, tariffs, availability flags,
    and equipment configuration. The weighted score uses min-max normalized
    objective values over the feasible candidate set; weights are preferences,
    not probabilities or economic coefficients.
    """
    evaluated = []
    for policy in ("battery_first", "grid_first"):
        dispatch = dispatch_energy_system(inputs, config, policy=policy)
        audit = _audit(dispatch)
        summary = dispatch["summary"]
        objectives = {
            "estimated_energy_cost": float(summary["estimated_energy_cost"]),
            "unmet_load_kwh": float(summary["unmet_load_kwh"]),
            "renewable_curtailed_kwh": float(summary["renewable_curtailed_kwh"]),
            "battery_throughput_kwh": float(summary["battery_throughput_kwh"]),
        }
        evaluated.append({
            "policy": policy, "objectives": objectives,
            "summary": summary, "audit": audit,
            "feasible": audit["passed"],
            "dispatch": dispatch,
        })
    feasible = [row for row in evaluated if row["feasible"]]
    if not feasible:
        raise OptimizationError("No feasible dispatch candidate passed the physical audit")
    pareto = [row for row in feasible if not any(
        other is not row and _dominates(other, row) for other in feasible
    )]
    keys = ("estimated_energy_cost", "unmet_load_kwh",
            "renewable_curtailed_kwh", "battery_throughput_kwh")
    weight_values = (weights.cost, weights.reliability,
                     weights.curtailment, 0.0)
    ranges = {
        key: (min(row["objectives"][key] for row in pareto),
              max(row["objectives"][key] for row in pareto))
        for key in keys
    }
    def score(row: dict) -> float:
        total = 0.0
        for key, weight in zip(keys, weight_values):
            low, high = ranges[key]
            normalized = 0.0 if high - low <= 1e-12 else (
                row["objectives"][key] - low
            ) / (high - low)
            total += weight * normalized
        return total
    recommended = min(pareto, key=lambda row: (score(row), row["policy"]))
    return {
        "candidate_count": len(evaluated),
        "feasible_count": len(feasible),
        "pareto_count": len(pareto),
        "candidates": evaluated,
        "pareto_policies": [row["policy"] for row in pareto],
        "recommendation": {
            "policy": recommended["policy"],
            "weighted_score": score(recommended),
            "weights": {
                "cost": weights.cost, "reliability": weights.reliability,
                "curtailment": weights.curtailment,
                "battery_throughput_tiebreak_only": 0.0,
            },
            "objectives": recommended["objectives"],
        },
        "model_scope": {
            "optimizer": "bounded_two_policy_pareto_screening",
            "not_global_hourly_setpoint_optimization": True,
            "uses_shared_physical_dispatch_engine": True,
            "same_inputs_for_all_candidates": True,
            "synthetic_or_user_supplied_inputs_only": True,
            "not_a_controller": True,
        },
    }



def optimize_energy_system_schedule(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    weights: OptimizationWeights = OptimizationWeights(),
    population_size: int = 32,
    generations: int = 20,
    mutation_rate: float = 0.08,
    seed: int = 20261108,
    max_horizon_steps: int = 168,
) -> dict:
    """Search timestep-specific battery/grid priority schedules with NSGA-II.

    Each gene selects one of the physical simulator's two dispatch priorities
    for one timestep. This is a real horizon-dependent schedule search, but
    not a search over arbitrary kW set-points or unit commitment binaries.
    """
    n = len(inputs.load_kw)
    if n < 1:
        raise OptimizationError("optimization horizon must contain at least one step")
    if n > max_horizon_steps:
        raise OptimizationError(
            f"optimization horizon has {n} steps; configured maximum is {max_horizon_steps}"
        )
    if population_size < 4:
        raise OptimizationError("population_size must be >= 4")
    if generations < 1:
        raise OptimizationError("generations must be >= 1")
    if isinstance(mutation_rate, bool) or not isinstance(mutation_rate, (int, float)) or not 0 <= mutation_rate <= 1:
        raise OptimizationError("mutation_rate must be within [0, 1]")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise OptimizationError("seed must be an integer")
    rng = random.Random(seed)
    cache: dict[tuple[int, ...], dict] = {}

    def evaluate(genome: tuple[int, ...]) -> dict:
        if genome not in cache:
            schedule = tuple(
                "battery_first" if gene == 0 else "grid_first" for gene in genome
            )
            dispatch = dispatch_energy_system(
                inputs, config, policy_schedule=schedule
            )
            audit = _audit(dispatch)
            summary = dispatch["summary"]
            objectives = {
                "estimated_energy_cost": float(summary["estimated_energy_cost"]),
                "unmet_load_kwh": float(summary["unmet_load_kwh"]),
                "renewable_curtailed_kwh": float(summary["renewable_curtailed_kwh"]),
                "battery_throughput_kwh": float(summary["battery_throughput_kwh"]),
            }
            cache[genome] = {
                "genome": list(genome),
                "policy_schedule": list(schedule),
                "objectives": objectives,
                "summary": summary,
                "audit": audit,
                "feasible": audit["passed"],
                "dispatch": dispatch,
            }
        return cache[genome]

    def dominates_candidate(a: dict, b: dict) -> bool:
        keys = ("estimated_energy_cost", "unmet_load_kwh",
                "renewable_curtailed_kwh", "battery_throughput_kwh")
        av = [a["objectives"][key] for key in keys]
        bv = [b["objectives"][key] for key in keys]
        if a["feasible"] != b["feasible"]:
            return a["feasible"]
        if not a["feasible"]:
            return False
        return all(x <= y + 1e-9 for x, y in zip(av, bv)) and any(
            x < y - 1e-9 for x, y in zip(av, bv)
        )

    def pareto_front(rows: list[dict]) -> list[dict]:
        feasible_rows = [row for row in rows if row["feasible"]]
        return [row for row in feasible_rows if not any(
            other is not row and dominates_candidate(other, row)
            for other in feasible_rows
        )]

    zero = tuple(0 for _ in range(n))
    one = tuple(1 for _ in range(n))
    evaluate(zero)
    evaluate(one)
    population = [zero, one]
    maximum_unique_schedules = min(population_size, 2 ** n)
    while len(population) < maximum_unique_schedules:
        genome = tuple(rng.randrange(2) for _ in range(n))
        if genome not in population:
            evaluate(genome)
            population.append(genome)

    def score(row: dict, front: list[dict]) -> float:
        keys = ("estimated_energy_cost", "unmet_load_kwh",
                "renewable_curtailed_kwh")
        weight_values = (weights.cost, weights.reliability, weights.curtailment)
        total = 0.0
        for key, weight in zip(keys, weight_values):
            low = min(item["objectives"][key] for item in front)
            high = max(item["objectives"][key] for item in front)
            value = row["objectives"][key]
            normalized = 0.0 if high - low <= 1e-12 else (value - low) / (high - low)
            total += weight * normalized
        return total

    for _ in range(generations):
        front = pareto_front([evaluate(genome) for genome in population])
        if not front:
            raise OptimizationError("No schedule passed the physical dispatch audit")
        # Tournament selection by Pareto dominance, then normalized objective score.
        offspring: list[tuple[int, ...]] = []
        while len(offspring) < population_size:
            parents = rng.sample(population, 2)
            a, b = evaluate(parents[0]), evaluate(parents[1])
            if dominates_candidate(a, b):
                parent = parents[0]
            elif dominates_candidate(b, a):
                parent = parents[1]
            else:
                parent = min(
                    parents,
                    key=lambda genome: (score(evaluate(genome), front), genome),
                )
            mate = rng.choice(population)
            cut = rng.randrange(n) if n > 1 else 0
            child = tuple(
                (parent[i] if i <= cut else mate[i]) for i in range(n)
            )
            child = tuple(
                1 - gene if rng.random() < mutation_rate else gene
                for gene in child
            )
            offspring.append(child)
            evaluate(child)
        combined = list(dict.fromkeys(population + offspring))
        combined_rows = [evaluate(genome) for genome in combined]
        next_front = pareto_front(combined_rows)
        # Keep Pareto members first; fill remaining slots with best scalar score.
        selected = sorted(
            next_front,
            key=lambda row: (score(row, next_front), tuple(row["genome"])),
        )
        selected_genomes = [tuple(row["genome"]) for row in selected[:population_size]]
        if len(selected_genomes) < population_size:
            remaining = [
                row for row in combined_rows
                if tuple(row["genome"]) not in selected_genomes
            ]
            remaining.sort(
                key=lambda row: (
                    not row["feasible"],
                    score(row, next_front) if row["feasible"] else float("inf"),
                    tuple(row["genome"]),
                )
            )
            selected_genomes.extend(
                tuple(row["genome"])
                for row in remaining[:population_size - len(selected_genomes)]
            )
        population = selected_genomes

    archive = pareto_front(list(cache.values()))
    if not archive:
        raise OptimizationError("No schedule passed the physical dispatch audit")
    archive.sort(
        key=lambda row: (
            score(row, archive),
            tuple(row["genome"]),
        )
    )
    recommended = archive[0]
    return {
        "algorithm": "seeded_binary_schedule_evolutionary_pareto_search",
        "candidate_count": len(cache),
        "feasible_count": sum(row["feasible"] for row in cache.values()),
        "pareto_count": len(archive),
        "population_size": population_size,
        "generations": generations,
        "seed": seed,
        "horizon_steps": n,
        "pareto_schedules": [
            {
                "policy_schedule": row["policy_schedule"],
                "objectives": row["objectives"],
            }
            for row in archive
        ],
        "recommendation": {
            "policy_schedule": recommended["policy_schedule"],
            "weighted_score": score(recommended, archive),
            "weights": {
                "cost": weights.cost,
                "reliability": weights.reliability,
                "curtailment": weights.curtailment,
            },
            "objectives": recommended["objectives"],
            "dispatch": recommended["dispatch"],
        },
        "model_scope": {
            "decision_variables": "one binary battery_first/grid_first priority per timestep",
            "search": "stochastic evolutionary heuristic; not guaranteed global optimum",
            "uses_shared_physical_dispatch_engine": True,
            "same_inputs_for_all_candidates": True,
            "synthetic_or_user_supplied_inputs_only": True,
            "not_arbitrary_kw_setpoint_optimization": True,
            "not_a_controller": True,
        },
    }
