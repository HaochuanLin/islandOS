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
    battery_wear: float = 0.0

    def __post_init__(self) -> None:
        values = (self.cost, self.reliability, self.curtailment, self.battery_wear)
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
                     weights.curtailment, weights.battery_wear)
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
                "battery_wear": weights.battery_wear,
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
                "renewable_curtailed_kwh", "battery_throughput_kwh")
        weight_values = (weights.cost, weights.reliability, weights.curtailment, weights.battery_wear)
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
    archive = sorted(
        archive,
        key=lambda row: (
            score(row, archive),
            tuple(row["genome"]),
        ),
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
                "battery_wear": weights.battery_wear,
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



def optimize_battery_power_schedule(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    weights: OptimizationWeights = OptimizationWeights(),
    population_size: int = 32,
    generations: int = 20,
    mutation_rate: float = 0.12,
    seed: int = 20261108,
    max_horizon_steps: int = 168,
) -> dict:
    """Search bounded continuous battery charge/discharge set-points offline.

    Negative genes request charging from renewable surplus only; positive genes
    request discharge to serve load. Grid and configured diesel cover residual
    demand through the shared physical simulator. This is not grid charging,
    diesel commitment optimization, or a global mixed-integer solution.
    """
    if config.battery is None:
        raise OptimizationError("a configured battery is required for battery set-point optimization")
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
    if isinstance(mutation_rate, bool) or not isinstance(mutation_rate, (int, float)) or not math.isfinite(float(mutation_rate)) or not 0 <= mutation_rate <= 1:
        raise OptimizationError("mutation_rate must be finite and within [0, 1]")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise OptimizationError("seed must be an integer")

    battery = config.battery
    lower, upper = -float(battery.max_charge_kw), float(battery.max_discharge_kw)
    span = upper - lower
    rng = random.Random(seed)
    cache: dict[tuple[float, ...], dict] = {}

    def evaluate(genome: tuple[float, ...]) -> dict:
        if genome not in cache:
            dispatch = dispatch_energy_system(
                EnergySystemInputs(
                    pv_generation_kw=inputs.pv_generation_kw,
                    wind_generation_kw=inputs.wind_generation_kw,
                    load_kw=inputs.load_kw,
                    grid_price_per_kwh=inputs.grid_price_per_kwh,
                    grid_available=inputs.grid_available,
                    diesel_available=inputs.diesel_available,
                    grid_export_price_per_kwh=inputs.grid_export_price_per_kwh,
                    grid_export_available=inputs.grid_export_available,
                    diesel_fuel_delivery_liters=inputs.diesel_fuel_delivery_liters,
                    battery_power_setpoint_kw=genome,
                    diesel_commitment_schedule=inputs.diesel_commitment_schedule,
                ),
                config,
                policy="battery_first",
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
                "setpoints_kw": list(genome),
                "objectives": objectives,
                "summary": summary,
                "audit": audit,
                "feasible": audit["passed"],
                "dispatch": dispatch,
            }
        return cache[genome]

    def dominates_candidate(a: dict, b: dict) -> bool:
        return a["feasible"] and (
            not b["feasible"] or _dominates(a, b)
        )

    def pareto_front(rows: list[dict]) -> list[dict]:
        feasible_rows = [row for row in rows if row["feasible"]]
        return [
            row for row in feasible_rows
            if not any(other is not row and _dominates(other, row) for other in feasible_rows)
        ]

    def score(row: dict, front: list[dict]) -> float:
        keys = (
            "estimated_energy_cost", "unmet_load_kwh",
            "renewable_curtailed_kwh", "battery_throughput_kwh",
        )
        objective_weights = (
            weights.cost, weights.reliability, weights.curtailment, weights.battery_wear,
        )
        total = 0.0
        for key, weight in zip(keys, objective_weights):
            low = min(item["objectives"][key] for item in front)
            high = max(item["objectives"][key] for item in front)
            value = row["objectives"][key]
            normalized = 0.0 if high - low <= 1e-12 else (value - low) / (high - low)
            total += weight * normalized
        return total

    zero = tuple(0.0 for _ in range(n))
    population = [zero]
    while len(population) < population_size:
        genome = tuple(rng.uniform(lower, upper) for _ in range(n))
        if genome not in population:
            population.append(genome)
            evaluate(genome)
    evaluate(zero)

    for _ in range(generations):
        current_front = pareto_front([evaluate(genome) for genome in population])
        if not current_front:
            raise OptimizationError("No battery schedule passed the physical dispatch audit")
        offspring: list[tuple[float, ...]] = []
        while len(offspring) < population_size:
            parents = rng.sample(population, 2)
            rows = [evaluate(genome) for genome in parents]
            if dominates_candidate(rows[0], rows[1]):
                parent = parents[0]
            elif dominates_candidate(rows[1], rows[0]):
                parent = parents[1]
            else:
                parent = min(
                    parents,
                    key=lambda genome: (score(evaluate(genome), current_front), genome),
                )
            mate = rng.choice(population)
            child_values = []
            for index in range(n):
                alpha = rng.random()
                value = alpha * parent[index] + (1.0 - alpha) * mate[index]
                if rng.random() < mutation_rate:
                    value += rng.gauss(0.0, span * 0.15)
                child_values.append(round(min(upper, max(lower, value)), 8))
            child = tuple(child_values)
            offspring.append(child)
            evaluate(child)
        combined = list(dict.fromkeys(population + offspring))
        combined_rows = [evaluate(genome) for genome in combined]
        next_front = pareto_front(combined_rows)
        if not next_front:
            raise OptimizationError("No battery schedule passed the physical dispatch audit")
        selected = sorted(
            next_front,
            key=lambda row: (score(row, next_front), tuple(row["setpoints_kw"])),
        )
        selected_genomes = [tuple(row["setpoints_kw"]) for row in selected[:population_size]]
        if len(selected_genomes) < population_size:
            remaining = [
                row for row in combined_rows
                if tuple(row["setpoints_kw"]) not in selected_genomes
            ]
            remaining.sort(
                key=lambda row: (
                    not row["feasible"],
                    score(row, next_front) if row["feasible"] else float("inf"),
                    tuple(row["setpoints_kw"]),
                )
            )
            selected_genomes.extend(
                tuple(row["setpoints_kw"])
                for row in remaining[:population_size - len(selected_genomes)]
            )
        population = selected_genomes

    archive = pareto_front(list(cache.values()))
    if not archive:
        raise OptimizationError("No battery schedule passed the physical dispatch audit")
    archive = sorted(
        archive,
        key=lambda row: (score(row, archive), tuple(row["setpoints_kw"])),
    )
    recommended = archive[0]
    return {
        "algorithm": "seeded_real_valued_evolutionary_pareto_search",
        "decision_variable": "signed battery power set-point in kW per timestep",
        "sign_convention": "negative=charge from renewable surplus only; positive=discharge to load",
        "candidate_count": len(cache),
        "feasible_count": sum(row["feasible"] for row in cache.values()),
        "pareto_count": len(archive),
        "population_size": population_size,
        "generations": generations,
        "seed": seed,
        "horizon_steps": n,
        "pareto_schedules": [
            {"setpoints_kw": row["setpoints_kw"], "objectives": row["objectives"]}
            for row in archive
        ],
        "recommendation": {
            "setpoints_kw": recommended["setpoints_kw"],
            "weighted_score": score(recommended, archive),
            "weights": {
                "cost": weights.cost,
                "reliability": weights.reliability,
                "curtailment": weights.curtailment,
                "battery_wear": weights.battery_wear,
            },
            "objectives": recommended["objectives"],
            "dispatch": recommended["dispatch"],
        },
        "model_scope": {
            "uses_shared_physical_dispatch_engine": True,
            "same_inputs_for_all_candidates": True,
            "setpoints_clipped_to_configured_battery_power_limits": True,
            "battery_soc_efficiency_and_capacity_fade_enforced_by_simulator": True,
            "grid_and_diesel_cover_residual_load": True,
            "grid_charging_not_modeled": True,
            "diesel_commitment_not_optimized": True,
            "not_global_mixed_integer_optimization": True,
            "not_a_controller": True,
        },
    }



def optimize_battery_and_diesel_schedule(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    weights: OptimizationWeights = OptimizationWeights(),
    population_size: int = 32,
    generations: int = 20,
    mutation_rate: float = 0.12,
    seed: int = 20261108,
    max_horizon_steps: int = 168,
    flexible_load_energy_kwh: float | None = None,
    flexible_load_available_steps: Sequence[bool] | None = None,
    flexible_load_max_power_kw: float | None = None,
    additional_scenarios: dict[str, EnergySystemInputs] | None = None,
) -> dict:
    """Jointly search battery, diesel, and optional aggregate flexible-load schedules.

    The shared simulator clips battery/diesel requests to their configured
    physical limits. When enabled, flexible-load energy is conserved inside
    its availability window and per-step power envelope.
    """
    if config.battery is None or config.diesel is None:
        raise OptimizationError("both a configured battery and diesel unit are required")
    if inputs.diesel_available is None:
        raise OptimizationError("diesel_available must be explicitly supplied")
    n = len(inputs.load_kw)
    if n < 1:
        raise OptimizationError("optimization horizon must contain at least one step")
    if n > max_horizon_steps:
        raise OptimizationError(
            f"optimization horizon has {n} steps; configured maximum is {max_horizon_steps}"
        )
    scenario_inputs = {"nominal": inputs}
    if additional_scenarios is not None:
        if not isinstance(additional_scenarios, dict) or not additional_scenarios:
            raise OptimizationError("additional_scenarios must be a non-empty mapping when supplied")
        for scenario_name, scenario in additional_scenarios.items():
            if not isinstance(scenario_name, str) or not scenario_name.strip() or scenario_name == "nominal":
                raise OptimizationError("additional scenario names must be non-empty and must not be 'nominal'")
            if not isinstance(scenario, EnergySystemInputs):
                raise OptimizationError(f"additional scenario {scenario_name!r} must use EnergySystemInputs")
            if len(scenario.load_kw) != n:
                raise OptimizationError("all robust optimization scenarios must use the same horizon length")
            if scenario.diesel_available is None:
                raise OptimizationError(f"diesel_available must be explicitly supplied for scenario {scenario_name!r}")
            scenario_inputs[scenario_name] = scenario
    if population_size < 4:
        raise OptimizationError("population_size must be >= 4")
    if generations < 1:
        raise OptimizationError("generations must be >= 1")
    if isinstance(mutation_rate, bool) or not isinstance(mutation_rate, (int, float)) or not math.isfinite(float(mutation_rate)) or not 0 <= mutation_rate <= 1:
        raise OptimizationError("mutation_rate must be finite and within [0, 1]")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise OptimizationError("seed must be an integer")

    flexible_enabled = any(value is not None for value in (
        flexible_load_energy_kwh,
        flexible_load_available_steps,
        flexible_load_max_power_kw,
    ))
    if flexible_enabled and any(value is None for value in (
        flexible_load_energy_kwh,
        flexible_load_available_steps,
        flexible_load_max_power_kw,
    )):
        raise OptimizationError(
            "flexible-load energy, availability, and maximum power must be supplied together"
        )
    if flexible_enabled:
        if isinstance(flexible_load_energy_kwh, bool) or not isinstance(flexible_load_energy_kwh, (int, float)) or not math.isfinite(float(flexible_load_energy_kwh)) or flexible_load_energy_kwh <= 0:
            raise OptimizationError("flexible_load_energy_kwh must be finite and > 0")
        if isinstance(flexible_load_max_power_kw, bool) or not isinstance(flexible_load_max_power_kw, (int, float)) or not math.isfinite(float(flexible_load_max_power_kw)) or flexible_load_max_power_kw <= 0:
            raise OptimizationError("flexible_load_max_power_kw must be finite and > 0")
        flexible_availability = list(flexible_load_available_steps)
        if len(flexible_availability) != n or any(not isinstance(value, bool) for value in flexible_availability):
            raise OptimizationError(f"flexible_load_available_steps must contain exactly {n} boolean values")
        flexible_allowed = [i for i, enabled in enumerate(flexible_availability) if enabled]
        flexible_power_hours = float(flexible_load_energy_kwh) / config.dt_hours
        if flexible_power_hours > len(flexible_allowed) * float(flexible_load_max_power_kw) + 1e-9:
            raise OptimizationError("required flexible energy exceeds available-window power capacity")
    else:
        flexible_availability = [False] * n
        flexible_allowed = []
        flexible_power_hours = 0.0
        flexible_load_energy_kwh = 0.0
        flexible_load_max_power_kw = 0.0

    lower = -float(config.battery.max_charge_kw)
    upper = float(config.battery.max_discharge_kw)
    span = upper - lower
    rng = random.Random(seed)
    # Genome: battery kW, diesel commitment, diesel requested kW, flexible-load kW.
    Genome = tuple[
        tuple[float, ...], tuple[bool, ...],
        tuple[float, ...], tuple[float, ...], tuple[float, ...],
    ]
    cache: dict[Genome, dict] = {}

    def random_flexible_schedule() -> tuple[float, ...]:
        schedule = [0.0] * n
        if not flexible_enabled:
            return tuple(schedule)
        order = rng.sample(flexible_allowed, len(flexible_allowed))
        remaining = flexible_power_hours
        for position, timestep in enumerate(order):
            remaining_slots = len(order) - position - 1
            low_bound = max(
                0.0,
                remaining - remaining_slots * float(flexible_load_max_power_kw),
            )
            high_bound = min(float(flexible_load_max_power_kw), remaining)
            value = remaining if remaining_slots == 0 else rng.uniform(low_bound, high_bound)
            schedule[timestep] = value
            remaining -= value
        if order:
            schedule[order[-1]] += flexible_power_hours - sum(schedule)
        return tuple(round(value, 8) for value in schedule)


    def random_export_schedule() -> tuple[float, ...]:
        limit = float(config.grid_export_limit_kw)
        return tuple(
            round(rng.uniform(0.0, limit), 8) if limit > 0 else 0.0
            for _ in range(n)
        )

    def evaluate(genome: Genome) -> dict:
        if genome not in cache:
            setpoints, commitments, diesel_targets, flexible_schedule, export_schedule = genome
            if not math.isclose(
                sum(flexible_schedule) * config.dt_hours,
                float(flexible_load_energy_kwh),
                rel_tol=0,
                abs_tol=1e-6,
            ):
                raise OptimizationError("joint candidate does not conserve flexible-load energy")
            per_scenario = {}
            audit_errors = []
            dispatch_by_scenario = {}
            for scenario_name, source in scenario_inputs.items():
                candidate_inputs = EnergySystemInputs(
                    pv_generation_kw=source.pv_generation_kw,
                    wind_generation_kw=source.wind_generation_kw,
                    load_kw=source.load_kw,
                    flexible_load_kw=flexible_schedule,
                    critical_load_kw=source.critical_load_kw,
                    grid_price_per_kwh=source.grid_price_per_kwh,
                    grid_available=source.grid_available,
                    diesel_available=source.diesel_available,
                    grid_export_price_per_kwh=source.grid_export_price_per_kwh,
                    grid_export_available=source.grid_export_available,
                    diesel_fuel_delivery_liters=source.diesel_fuel_delivery_liters,
                    battery_power_setpoint_kw=setpoints,
                    diesel_commitment_schedule=commitments,
                    diesel_power_setpoint_kw=diesel_targets,
                    grid_export_power_setpoint_kw=export_schedule,
                )
                scenario_dispatch = dispatch_energy_system(candidate_inputs, config)
                scenario_audit = _audit(scenario_dispatch)
                scenario_summary = scenario_dispatch["summary"]
                scenario_objectives = {
                    "estimated_energy_cost": float(scenario_summary["estimated_energy_cost"]),
                    "unmet_load_kwh": float(scenario_summary["unmet_load_kwh"]),
                    "renewable_curtailed_kwh": float(scenario_summary["renewable_curtailed_kwh"]),
                    "battery_throughput_kwh": float(scenario_summary["battery_throughput_kwh"]),
                }
                per_scenario[scenario_name] = {
                    "objectives": scenario_objectives,
                    "summary": scenario_summary,
                    "audit": scenario_audit,
                }
                dispatch_by_scenario[scenario_name] = scenario_dispatch
                if not scenario_audit["passed"]:
                    audit_errors.extend(
                        f"{scenario_name}:{error}"
                        for error in scenario_audit["errors"]
                    )
            objective_keys = (
                "estimated_energy_cost", "unmet_load_kwh",
                "renewable_curtailed_kwh", "battery_throughput_kwh",
            )
            worst_case_objectives = {
                key: max(
                    row["objectives"][key] for row in per_scenario.values()
                )
                for key in objective_keys
            }
            nominal_dispatch = dispatch_by_scenario["nominal"]
            aggregate_audit = {
                "passed": not audit_errors,
                "errors": audit_errors,
                "scope": "all supplied scenario dispatches independently passed the physical audit",
            }
            cache[genome] = {
                "battery_setpoints_kw": list(setpoints),
                "diesel_commitment_schedule": list(commitments),
                "diesel_power_setpoint_kw": list(diesel_targets),
                "flexible_load_power_kw": list(flexible_schedule),
                "grid_export_power_setpoint_kw": list(export_schedule),
                "objectives": worst_case_objectives,
                "summary": nominal_dispatch["summary"],
                "audit": aggregate_audit,
                "feasible": aggregate_audit["passed"],
                "dispatch": nominal_dispatch,
                "scenario_results": per_scenario,
            }
        return cache[genome]

    def pareto_front(rows: list[dict]) -> list[dict]:
        feasible_rows = [row for row in rows if row["feasible"]]
        return [
            row for row in feasible_rows
            if not any(other is not row and _dominates(other, row) for other in feasible_rows)
        ]

    def score(row: dict, front: list[dict]) -> float:
        keys = (
            "estimated_energy_cost", "unmet_load_kwh",
            "renewable_curtailed_kwh", "battery_throughput_kwh",
        )
        objective_weights = (weights.cost, weights.reliability, weights.curtailment, weights.battery_wear)
        total = 0.0
        for key, weight in zip(keys, objective_weights):
            low = min(item["objectives"][key] for item in front)
            high = max(item["objectives"][key] for item in front)
            value = row["objectives"][key]
            normalized = 0.0 if high - low <= 1e-12 else (value - low) / (high - low)
            total += weight * normalized
        return total

    zero = tuple(0.0 for _ in range(n))
    off = tuple(False for _ in range(n))
    on = tuple(True for _ in range(n))
    diesel_off = tuple(0.0 for _ in range(n))
    diesel_full = tuple(float(config.diesel.rated_power_kw) for _ in range(n))
    population: list[Genome] = [
        (zero, off, diesel_off, random_flexible_schedule(), random_export_schedule()),
        (zero, on, diesel_full, random_flexible_schedule(), random_export_schedule()),
    ]
    while len(population) < population_size:
        genome: Genome = (
            tuple(round(rng.uniform(lower, upper), 8) for _ in range(n)),
            tuple(bool(rng.getrandbits(1)) for _ in range(n)),
            tuple(round(rng.uniform(0.0, config.diesel.rated_power_kw), 8) for _ in range(n)),
            random_flexible_schedule(),
            random_export_schedule(),
        )
        if genome not in population:
            population.append(genome)
            evaluate(genome)
    for genome in population:
        evaluate(genome)

    for _ in range(generations):
        front = pareto_front([evaluate(genome) for genome in population])
        if not front:
            raise OptimizationError("No joint battery/diesel schedule passed the physical audit")
        offspring: list[Genome] = []
        while len(offspring) < population_size:
            parents = rng.sample(population, 2)
            parent_rows = [evaluate(item) for item in parents]
            if parent_rows[0]["feasible"] and not parent_rows[1]["feasible"]:
                parent = parents[0]
            elif parent_rows[1]["feasible"] and not parent_rows[0]["feasible"]:
                parent = parents[1]
            elif _dominates(parent_rows[0], parent_rows[1]):
                parent = parents[0]
            elif _dominates(parent_rows[1], parent_rows[0]):
                parent = parents[1]
            else:
                parent = min(
                    parents,
                    key=lambda item: (
                        score(evaluate(item), front) if evaluate(item)["feasible"] else float("inf"),
                        item,
                    ),
                )
            mate = rng.choice(population)
            battery_child = []
            diesel_child = []
            diesel_power_child = []
            flexible_child = []
            export_child = []
            flexible_alpha = rng.random() if flexible_enabled else 0.5
            for index in range(n):
                alpha = rng.random()
                value = alpha * parent[0][index] + (1 - alpha) * mate[0][index]
                if rng.random() < mutation_rate:
                    value += rng.gauss(0.0, span * 0.15)
                battery_child.append(round(min(upper, max(lower, value)), 8))
                diesel_gene = parent[1][index] if rng.random() < 0.5 else mate[1][index]
                if rng.random() < mutation_rate:
                    diesel_gene = not diesel_gene
                diesel_child.append(diesel_gene)
                diesel_power = parent[2][index] if rng.random() < 0.5 else mate[2][index]
                if rng.random() < mutation_rate:
                    diesel_power += rng.gauss(0.0, config.diesel.rated_power_kw * 0.15)
                diesel_power_child.append(round(min(config.diesel.rated_power_kw, max(0.0, diesel_power)), 8))
                # One shared convex-combination coefficient preserves total energy.
                flexible_value = (
                    flexible_alpha * parent[3][index]
                    + (1 - flexible_alpha) * mate[3][index]
                )
                flexible_child.append(flexible_value)
                export_value = parent[4][index] if rng.random() < 0.5 else mate[4][index]
                if rng.random() < mutation_rate and config.grid_export_limit_kw > 0:
                    export_value += rng.gauss(0.0, config.grid_export_limit_kw * 0.15)
                export_child.append(round(min(config.grid_export_limit_kw, max(0.0, export_value)), 8))
            if flexible_enabled and len(flexible_allowed) > 1 and rng.random() < mutation_rate:
                donor, receiver = rng.sample(flexible_allowed, 2)
                transferable = min(
                    flexible_child[donor],
                    float(flexible_load_max_power_kw) - flexible_child[receiver],
                )
                if transferable > 1e-12:
                    amount = rng.uniform(0.0, transferable)
                    flexible_child[donor] -= amount
                    flexible_child[receiver] += amount
            flexible_tuple = [round(value, 8) for value in flexible_child]
            flexible_drift = flexible_power_hours - sum(flexible_tuple)
            if abs(flexible_drift) > 1e-9:
                for timestep in flexible_allowed:
                    proposed = flexible_tuple[timestep] + flexible_drift
                    if -1e-9 <= proposed <= float(flexible_load_max_power_kw) + 1e-9:
                        flexible_tuple[timestep] = min(
                            float(flexible_load_max_power_kw), max(0.0, proposed)
                        )
                        break
            child: Genome = (
                tuple(battery_child), tuple(diesel_child),
                tuple(diesel_power_child), tuple(flexible_tuple),
                tuple(export_child),
            )
            offspring.append(child)
            evaluate(child)
        combined = list(dict.fromkeys(population + offspring))
        combined_rows = [evaluate(genome) for genome in combined]
        next_front = pareto_front(combined_rows)
        if not next_front:
            raise OptimizationError("No joint battery/diesel schedule passed the physical audit")
        selected = sorted(
            next_front,
            key=lambda row: (
                score(row, next_front),
                tuple(row["battery_setpoints_kw"]),
                tuple(row["diesel_commitment_schedule"]),
                tuple(row["diesel_power_setpoint_kw"]),
                tuple(row["flexible_load_power_kw"]),
            ),
        )
        selected_genomes = [
            (
                tuple(row["battery_setpoints_kw"]),
                tuple(row["diesel_commitment_schedule"]),
                tuple(row["diesel_power_setpoint_kw"]),
                tuple(row["flexible_load_power_kw"]),
                tuple(row["grid_export_power_setpoint_kw"]),
            )
            for row in selected[:population_size]
        ]
        if len(selected_genomes) < population_size:
            remaining = [
                row for row in combined_rows
                if (
                    tuple(row["battery_setpoints_kw"]),
                    tuple(row["diesel_commitment_schedule"]),
                    tuple(row["diesel_power_setpoint_kw"]),
                    tuple(row["flexible_load_power_kw"]),
                    tuple(row["grid_export_power_setpoint_kw"]),
                ) not in selected_genomes
            ]
            remaining.sort(
                key=lambda row: (
                    not row["feasible"],
                    score(row, next_front) if row["feasible"] else float("inf"),
                    tuple(row["battery_setpoints_kw"]),
                    tuple(row["diesel_commitment_schedule"]),
                )
            )
            selected_genomes.extend(
                (
                    tuple(row["battery_setpoints_kw"]),
                    tuple(row["diesel_commitment_schedule"]),
                    tuple(row["diesel_power_setpoint_kw"]),
                    tuple(row["flexible_load_power_kw"]),
                    tuple(row["grid_export_power_setpoint_kw"]),
                )
                for row in remaining[:population_size - len(selected_genomes)]
            )
        population = selected_genomes

    archive = pareto_front(list(cache.values()))
    if not archive:
        raise OptimizationError("No joint battery/diesel schedule passed the physical audit")
    archive = sorted(
        archive,
        key=lambda row: (
            score(row, archive),
            tuple(row["battery_setpoints_kw"]),
            tuple(row["diesel_commitment_schedule"]),
            tuple(row["flexible_load_power_kw"]),
            tuple(row["grid_export_power_setpoint_kw"]),
        ),
    )
    recommended = archive[0]

    # Compare against transparent rule-based baselines on the exact same
    # scenario set and the recommended flexible-load profile.
    baseline_comparison = {
        "same_inputs_config_and_scenarios": True,
        "flexible_load_profile_held_equal": True,
        "scenario_names": list(scenario_inputs),
        "policies": {},
    }
    for baseline_policy in ("battery_first", "grid_first"):
        baseline_scenarios = {}
        for scenario_name, source in scenario_inputs.items():
            baseline_inputs = EnergySystemInputs(
                pv_generation_kw=source.pv_generation_kw,
                wind_generation_kw=source.wind_generation_kw,
                load_kw=source.load_kw,
                grid_price_per_kwh=source.grid_price_per_kwh,
                grid_available=source.grid_available,
                diesel_available=source.diesel_available,
                grid_export_price_per_kwh=source.grid_export_price_per_kwh,
                grid_export_available=source.grid_export_available,
                diesel_fuel_delivery_liters=source.diesel_fuel_delivery_liters,
                grid_export_power_setpoint_kw=recommended["grid_export_power_setpoint_kw"],
                flexible_load_kw=(
                    recommended["flexible_load_power_kw"] if flexible_enabled else None
                ),
                critical_load_kw=source.critical_load_kw,
            )
            baseline_dispatch = dispatch_energy_system(
                baseline_inputs, config, policy=baseline_policy
            )
            baseline_audit = _audit(baseline_dispatch)
            baseline_summary = baseline_dispatch["summary"]
            baseline_scenarios[scenario_name] = {
                "objectives": {
                    "estimated_energy_cost": float(baseline_summary["estimated_energy_cost"]),
                    "unmet_load_kwh": float(baseline_summary["unmet_load_kwh"]),
                    "renewable_curtailed_kwh": float(baseline_summary["renewable_curtailed_kwh"]),
                    "battery_throughput_kwh": float(baseline_summary["battery_throughput_kwh"]),
                },
                "audit_passed": baseline_audit["passed"],
                "audit_errors": baseline_audit["errors"],
                "summary": baseline_summary,
            }
        baseline_worst_case = {
            key: max(row["objectives"][key] for row in baseline_scenarios.values())
            for key in (
                "estimated_energy_cost", "unmet_load_kwh",
                "renewable_curtailed_kwh", "battery_throughput_kwh",
            )
        }
        baseline_comparison["policies"][baseline_policy] = {
            "scenario_results": baseline_scenarios,
            "worst_case_objectives": baseline_worst_case,
            "recommended_minus_baseline": {
                key: round(recommended["objectives"][key] - baseline_worst_case[key], 8)
                for key in baseline_worst_case
            },
            "all_scenarios_passed_audit": all(
                row["audit_passed"] for row in baseline_scenarios.values()
            ),
        }

    return {
        "algorithm": "seeded_mixed_real_binary_evolutionary_pareto_search",
        "decision_variables": {
            "battery": "signed continuous kW set-point per timestep",
            "diesel_commitment": "binary on/off commitment per timestep",
            "diesel_power": "continuous requested kW set-point per timestep",
            "flexible_load": (
                "continuous kW allocation per timestep with conserved energy and availability bounds"
                if flexible_enabled else "disabled"
            ),
            "grid_export": "continuous per-timestep export cap, bounded by interconnection rating",
        },
        "candidate_count": len(cache),
        "feasible_count": sum(row["feasible"] for row in cache.values()),
        "pareto_count": len(archive),
        "population_size": population_size,
        "generations": generations,
        "seed": seed,
        "horizon_steps": n,
        "scenario_count": len(scenario_inputs),
        "scenario_names": list(scenario_inputs),
        "robust_objective_aggregation": "worst_case_maximum_across_supplied_scenarios",
        "baseline_comparison": baseline_comparison,
        "pareto_schedules": [
            {
                "battery_setpoints_kw": row["battery_setpoints_kw"],
                "diesel_commitment_schedule": row["diesel_commitment_schedule"],
                "diesel_power_setpoint_kw": row["diesel_power_setpoint_kw"],
                "flexible_load_power_kw": row["flexible_load_power_kw"],
                "grid_export_power_setpoint_kw": row["grid_export_power_setpoint_kw"],
                "objectives": row["objectives"],
            }
            for row in archive
        ],
        "recommendation": {
            "battery_setpoints_kw": recommended["battery_setpoints_kw"],
            "diesel_commitment_schedule": recommended["diesel_commitment_schedule"],
            "diesel_power_setpoint_kw": recommended["diesel_power_setpoint_kw"],
            "flexible_load_power_kw": recommended["flexible_load_power_kw"],
            "grid_export_power_setpoint_kw": recommended["grid_export_power_setpoint_kw"],
            "weighted_score": score(recommended, archive),
            "weights": {
                "cost": weights.cost,
                "reliability": weights.reliability,
                "curtailment": weights.curtailment,
                "battery_wear": weights.battery_wear,
            },
            "objectives": recommended["objectives"],
            "dispatch": recommended["dispatch"],
            "scenario_results": {
                name: {
                    "objectives": row["objectives"],
                    "audit_passed": row["audit"]["passed"],
                    "summary": row["summary"],
                }
                for name, row in recommended["scenario_results"].items()
            },
        },
        "model_scope": {
            "uses_shared_physical_dispatch_engine": True,
            "battery_soc_efficiency_and_capacity_fade_enforced": True,
            "diesel_minimum_load_ramp_up_fuel_and_availability_enforced": True,
            "diesel_power_setpoint_optimized": True,
            "flexible_load_schedule_jointly_optimized": flexible_enabled,
            "flexible_load_energy_conserved": True,
            "flexible_load_availability_and_power_bounds_enforced": True,
            "same_decisions_replayed_across_all_scenarios": True,
            "objectives_use_worst_case_across_scenarios": True,
            "rule_based_baseline_comparison_included": True,
            "baseline_flexible_load_profile_held_equal": True,
            "scenario_probabilities_assumed": False,
            "robust_optimization_enabled": len(scenario_inputs) > 1,
            "critical_vs_flexible_load_priority_modeled": False,
            "grid_import_is_physical_residual_balance": True,
            "grid_export_setpoint_optimized": config.grid_export_limit_kw > 0,
            "stochastic_heuristic_not_global_optimum": True,
            "not_a_controller": True,
        },
    }



def optimize_flexible_load_schedule(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    energy_required_kwh: float,
    available_steps: Sequence[bool],
    max_power_kw: float,
    weights: OptimizationWeights = OptimizationWeights(),
    population_size: int = 32,
    generations: int = 20,
    mutation_rate: float = 0.2,
    seed: int = 20261109,
    max_horizon_steps: int = 168,
) -> dict:
    """Schedule one aggregate shiftable load within an availability window.

    The required flexible energy is conserved exactly (within numerical
    tolerance); only its timestep allocation is optimized. Existing battery
    and diesel set-points on inputs are held fixed and replayed unchanged.
    """
    n = len(inputs.load_kw)
    if n < 1:
        raise OptimizationError("optimization horizon must contain at least one step")
    if n > max_horizon_steps:
        raise OptimizationError(
            f"optimization horizon has {n} steps; configured maximum is {max_horizon_steps}"
        )
    if isinstance(energy_required_kwh, bool) or not isinstance(energy_required_kwh, (int, float)) or not math.isfinite(float(energy_required_kwh)) or energy_required_kwh <= 0:
        raise OptimizationError("energy_required_kwh must be finite and > 0")
    if isinstance(max_power_kw, bool) or not isinstance(max_power_kw, (int, float)) or not math.isfinite(float(max_power_kw)) or max_power_kw <= 0:
        raise OptimizationError("max_power_kw must be finite and > 0")
    try:
        availability = list(available_steps)
    except TypeError as exc:
        raise OptimizationError("available_steps must be a boolean sequence") from exc
    if len(availability) != n or any(not isinstance(value, bool) for value in availability):
        raise OptimizationError(f"available_steps must contain exactly {n} boolean values")
    if population_size < 4:
        raise OptimizationError("population_size must be >= 4")
    if generations < 1:
        raise OptimizationError("generations must be >= 1")
    if isinstance(mutation_rate, bool) or not isinstance(mutation_rate, (int, float)) or not math.isfinite(float(mutation_rate)) or not 0 <= mutation_rate <= 1:
        raise OptimizationError("mutation_rate must be finite and within [0, 1]")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise OptimizationError("seed must be an integer")

    allowed = [index for index, enabled in enumerate(availability) if enabled]
    required_power_hours = float(energy_required_kwh) / config.dt_hours
    capacity_power_hours = len(allowed) * float(max_power_kw)
    if required_power_hours > capacity_power_hours + 1e-9:
        raise OptimizationError(
            "required flexible energy exceeds available-window power capacity"
        )

    rng = random.Random(seed)
    cache: dict[tuple[float, ...], dict] = {}

    def make_random_schedule() -> tuple[float, ...]:
        schedule = [0.0] * n
        order = rng.sample(allowed, len(allowed))
        remaining = required_power_hours
        for position, timestep in enumerate(order):
            remaining_slots = len(order) - position - 1
            lower = max(0.0, remaining - remaining_slots * float(max_power_kw))
            upper = min(float(max_power_kw), remaining)
            value = remaining if remaining_slots == 0 else rng.uniform(lower, upper)
            schedule[timestep] = value
            remaining -= value
        if order:
            schedule[order[-1]] += required_power_hours - sum(schedule)
        return tuple(round(value, 8) for value in schedule)

    def evaluate(schedule: tuple[float, ...]) -> dict:
        if schedule not in cache:
            flexible_energy = sum(schedule) * config.dt_hours
            if not math.isclose(
                flexible_energy, energy_required_kwh, rel_tol=0, abs_tol=1e-6
            ):
                raise OptimizationError("candidate does not conserve required flexible energy")
            candidate_inputs = EnergySystemInputs(
                pv_generation_kw=inputs.pv_generation_kw,
                wind_generation_kw=inputs.wind_generation_kw,
                load_kw=[
                    float(base) + flexible
                    for base, flexible in zip(inputs.load_kw, schedule)
                ],
                grid_price_per_kwh=inputs.grid_price_per_kwh,
                grid_available=inputs.grid_available,
                diesel_available=inputs.diesel_available,
                grid_export_price_per_kwh=inputs.grid_export_price_per_kwh,
                grid_export_available=inputs.grid_export_available,
                diesel_fuel_delivery_liters=inputs.diesel_fuel_delivery_liters,
                battery_power_setpoint_kw=inputs.battery_power_setpoint_kw,
                diesel_commitment_schedule=inputs.diesel_commitment_schedule,
                diesel_power_setpoint_kw=inputs.diesel_power_setpoint_kw,
            )
            dispatch = dispatch_energy_system(candidate_inputs, config)
            audit = _audit(dispatch)
            summary = dispatch["summary"]
            objectives = {
                "estimated_energy_cost": float(summary["estimated_energy_cost"]),
                "unmet_load_kwh": float(summary["unmet_load_kwh"]),
                "renewable_curtailed_kwh": float(summary["renewable_curtailed_kwh"]),
                "battery_throughput_kwh": float(summary["battery_throughput_kwh"]),
            }
            cache[schedule] = {
                "flexible_load_power_kw": list(schedule),
                "objectives": objectives,
                "summary": summary,
                "audit": audit,
                "feasible": audit["passed"],
                "dispatch": dispatch,
            }
        return cache[schedule]

    def pareto_front(rows: list[dict]) -> list[dict]:
        feasible_rows = [row for row in rows if row["feasible"]]
        return [
            row for row in feasible_rows
            if not any(other is not row and _dominates(other, row) for other in feasible_rows)
        ]

    def score(row: dict, front: list[dict]) -> float:
        keys = (
            "estimated_energy_cost", "unmet_load_kwh",
            "renewable_curtailed_kwh", "battery_throughput_kwh",
        )
        objective_weights = (
            weights.cost, weights.reliability,
            weights.curtailment, weights.battery_wear,
        )
        total = 0.0
        for key, weight in zip(keys, objective_weights):
            low = min(item["objectives"][key] for item in front)
            high = max(item["objectives"][key] for item in front)
            value = row["objectives"][key]
            normalized = 0.0 if high - low <= 1e-12 else (value - low) / (high - low)
            total += weight * normalized
        return total

    population = []
    while len(population) < population_size:
        genome = make_random_schedule()
        population.append(genome)
        evaluate(genome)

    for _ in range(generations):
        front = pareto_front([evaluate(genome) for genome in population])
        if not front:
            raise OptimizationError("No flexible-load schedule passed the physical audit")
        offspring: list[tuple[float, ...]] = []
        while len(offspring) < population_size:
            parents = rng.sample(population, 2)
            parent_rows = [evaluate(item) for item in parents]
            if _dominates(parent_rows[0], parent_rows[1]):
                parent = parents[0]
            elif _dominates(parent_rows[1], parent_rows[0]):
                parent = parents[1]
            else:
                parent = min(
                    parents,
                    key=lambda item: (score(evaluate(item), front), item),
                )
            mate = rng.choice(population)
            alpha = rng.random()
            child = [
                alpha * parent[index] + (1 - alpha) * mate[index]
                for index in range(n)
            ]
            if len(allowed) > 1 and rng.random() < mutation_rate:
                donor, receiver = rng.sample(allowed, 2)
                transferable = min(child[donor], float(max_power_kw) - child[receiver])
                if transferable > 1e-12:
                    amount = rng.uniform(0.0, transferable)
                    child[donor] -= amount
                    child[receiver] += amount
            child_tuple = tuple(round(value, 8) for value in child)
            drift = required_power_hours - sum(child_tuple)
            if abs(drift) > 1e-9:
                mutable = list(child_tuple)
                for index in allowed:
                    proposed = mutable[index] + drift
                    if -1e-9 <= proposed <= float(max_power_kw) + 1e-9:
                        mutable[index] = min(float(max_power_kw), max(0.0, proposed))
                        break
                child_tuple = tuple(round(value, 8) for value in mutable)
            offspring.append(child_tuple)
            evaluate(child_tuple)

        combined = list(dict.fromkeys(population + offspring))
        combined_rows = [evaluate(genome) for genome in combined]
        next_front = pareto_front(combined_rows)
        if not next_front:
            raise OptimizationError("No flexible-load schedule passed the physical audit")
        selected = sorted(
            next_front,
            key=lambda row: (
                score(row, next_front),
                tuple(row["flexible_load_power_kw"]),
            ),
        )
        selected_genomes = [
            tuple(row["flexible_load_power_kw"])
            for row in selected[:population_size]
        ]
        if len(selected_genomes) < population_size:
            remaining = [
                row for row in combined_rows
                if tuple(row["flexible_load_power_kw"]) not in selected_genomes
            ]
            remaining.sort(
                key=lambda row: (
                    not row["feasible"],
                    score(row, next_front) if row["feasible"] else float("inf"),
                    tuple(row["flexible_load_power_kw"]),
                )
            )
            selected_genomes.extend(
                tuple(row["flexible_load_power_kw"])
                for row in remaining[:population_size - len(selected_genomes)]
            )
        population = selected_genomes

    archive = pareto_front(list(cache.values()))
    if not archive:
        raise OptimizationError("No flexible-load schedule passed the physical audit")
    archive = sorted(
        archive,
        key=lambda row: (
            score(row, archive),
            tuple(row["flexible_load_power_kw"]),
        ),
    )
    recommended = archive[0]
    return {
        "algorithm": "seeded_real_valued_flexible_load_pareto_search",
        "decision_variable": "flexible-load kW allocation per timestep",
        "candidate_count": len(cache),
        "feasible_count": sum(row["feasible"] for row in cache.values()),
        "pareto_count": len(archive),
        "population_size": population_size,
        "generations": generations,
        "seed": seed,
        "horizon_steps": n,
        "required_flexible_energy_kwh": float(energy_required_kwh),
        "available_steps": list(availability),
        "max_power_kw": float(max_power_kw),
        "pareto_schedules": [
            {
                "flexible_load_power_kw": row["flexible_load_power_kw"],
                "objectives": row["objectives"],
            }
            for row in archive
        ],
        "recommendation": {
            "flexible_load_power_kw": recommended["flexible_load_power_kw"],
            "weighted_score": score(recommended, archive),
            "weights": {
                "cost": weights.cost,
                "reliability": weights.reliability,
                "curtailment": weights.curtailment,
                "battery_wear": weights.battery_wear,
            },
            "objectives": recommended["objectives"],
            "dispatch": recommended["dispatch"],
        },
        "model_scope": {
            "required_flexible_energy_conserved": True,
            "per_step_power_and_availability_bounds_enforced": True,
            "same_base_inputs_for_all_candidates": True,
            "fixed_battery_and_diesel_schedules_preserved": True,
            "flexible_load_added_to_base_electrical_load": True,
            "not_jointly_optimized_with_battery_or_diesel_decisions": True,
            "critical_vs_flexible_load_priority_modeled": False,
            "flexible_load_shedding_modeled": False,
            "stochastic_heuristic_not_guaranteed_global_optimum": True,
            "not_a_controller": True,
        },
    }


def diagnose_dispatch_shortfalls(
    dispatch: dict,
    config: EnergySystemConfig,
    *,
    tolerance_kw: float = 1e-8,
) -> list[dict]:
    """Explain likely operational limits behind unmet load without guessing a single cause."""
    if (
        isinstance(tolerance_kw, bool)
        or not isinstance(tolerance_kw, (int, float))
        or not math.isfinite(float(tolerance_kw))
        or tolerance_kw < 0
    ):
        raise OptimizationError("tolerance_kw must be finite and non-negative")
    diagnostics = []
    previous_diesel_kw = 0.0
    for index, row in enumerate(dispatch.get("rows", [])):
        unmet = float(row.get("unmet_load_kw", 0.0))
        if unmet <= tolerance_kw:
            previous_diesel_kw = float(row.get("diesel_generation_kw", 0.0))
            continue
        causes: list[str] = []
        if not row.get("grid_available", False):
            causes.append("grid_unavailable")
        elif row.get("grid_import_kw", 0.0) >= config.grid_import_limit_kw - tolerance_kw:
            causes.append("grid_import_limit_reached")

        if config.battery is None:
            causes.append("battery_not_configured")
        elif row.get("battery_soc") is not None and row["battery_soc"] <= config.battery.min_soc + tolerance_kw:
            causes.append("battery_minimum_soc_reached")
        elif row.get("battery_discharge_kw", 0.0) >= config.battery.max_discharge_kw - tolerance_kw:
            causes.append("battery_discharge_power_limit_reached")
        elif row.get("battery_power_setpoint_kw") is not None and row["battery_power_setpoint_kw"] <= tolerance_kw:
            causes.append("battery_setpoint_restricts_discharge")

        residual_before_diesel = max(
            0.0,
            float(row.get("load_kw", 0.0))
            - float(row.get("renewable_direct_to_load_kw", 0.0))
            - float(row.get("battery_discharge_kw", 0.0))
            - float(row.get("grid_import_kw", 0.0)),
        )
        if config.diesel is None:
            causes.append("diesel_not_configured")
        elif not row.get("diesel_available", False):
            causes.append("diesel_unavailable")
        elif row.get("diesel_committed") is False:
            causes.append("diesel_not_committed")
        elif residual_before_diesel + tolerance_kw < config.diesel.min_stable_power_kw:
            causes.append("residual_below_diesel_minimum_stable_output")
        elif (
            config.diesel.initial_fuel_liters is not None
            and row.get("diesel_fuel_remaining_liters") is not None
            and row["diesel_fuel_remaining_liters"] <= tolerance_kw
        ):
            causes.append("diesel_fuel_exhausted")
        elif (
            previous_diesel_kw > 0
            and config.diesel.ramp_up_kw_per_hour is not None
            and residual_before_diesel > previous_diesel_kw
            + config.diesel.ramp_up_kw_per_hour * config.dt_hours + tolerance_kw
        ):
            causes.append("diesel_ramp_up_limit_reached")
        elif residual_before_diesel > config.diesel.rated_power_kw + tolerance_kw:
            causes.append("diesel_rated_power_limit_reached")

        if not causes:
            causes.append("unmet_load_remains_after_configured_dispatch_limits")
        diagnostics.append({
            "timestep": index,
            "unmet_load_kw": unmet,
            "likely_limiting_factors": causes,
            "interpretation": "Potential contributing limits; multiple causes may apply and require operator review",
        })
        previous_diesel_kw = float(row.get("diesel_generation_kw", 0.0))
    return diagnostics


def evaluate_schedule_robustness(
    scenarios: dict[str, EnergySystemInputs],
    config: EnergySystemConfig,
    *,
    battery_power_setpoint_kw: Sequence[float] | None = None,
    diesel_commitment_schedule: Sequence[bool] | None = None,
    diesel_power_setpoint_kw: Sequence[float] | None = None,
    unmet_load_tolerance_kwh: float = 1e-8,
) -> dict:
    """Evaluate one common dispatch schedule against multiple operating scenarios.

    The same decision schedule is replayed against every scenario. This is a
    robustness screen, not a stochastic optimizer: it reports scenario-specific
    outcomes and worst-case exposure without claiming scenario probabilities.
    """
    if not isinstance(scenarios, dict) or not scenarios:
        raise OptimizationError("scenarios must be a non-empty mapping")
    if (
        isinstance(unmet_load_tolerance_kwh, bool)
        or not isinstance(unmet_load_tolerance_kwh, (int, float))
        or not math.isfinite(float(unmet_load_tolerance_kwh))
        or unmet_load_tolerance_kwh < 0
    ):
        raise OptimizationError("unmet_load_tolerance_kwh must be finite and non-negative")

    normalized_scenarios: list[tuple[str, EnergySystemInputs]] = []
    for name, scenario_inputs in scenarios.items():
        if not isinstance(name, str) or not name.strip():
            raise OptimizationError("scenario names must be non-empty strings")
        if not isinstance(scenario_inputs, EnergySystemInputs):
            raise OptimizationError(f"scenario {name!r} must use EnergySystemInputs")
        normalized_scenarios.append((name, scenario_inputs))

    horizons = {len(item.load_kw) for _, item in normalized_scenarios}
    if len(horizons) != 1:
        raise OptimizationError("all robustness scenarios must use the same horizon length")
    horizon = next(iter(horizons))
    if horizon < 1:
        raise OptimizationError("robustness scenario horizon must contain at least one step")

    for name, values in (
        ("battery_power_setpoint_kw", battery_power_setpoint_kw),
        ("diesel_commitment_schedule", diesel_commitment_schedule),
        ("diesel_power_setpoint_kw", diesel_power_setpoint_kw),
    ):
        if values is not None and (isinstance(values, (str, bytes)) or len(values) != horizon):
            raise OptimizationError(f"{name} must contain exactly {horizon} values")

    results: dict[str, dict] = {}
    objective_keys = (
        "estimated_energy_cost",
        "unmet_load_kwh",
        "renewable_curtailed_kwh",
        "battery_throughput_kwh",
    )
    for name, original in normalized_scenarios:
        replay = EnergySystemInputs(
            pv_generation_kw=original.pv_generation_kw,
            wind_generation_kw=original.wind_generation_kw,
            load_kw=original.load_kw,
            grid_price_per_kwh=original.grid_price_per_kwh,
            grid_available=original.grid_available,
            diesel_available=original.diesel_available,
            grid_export_price_per_kwh=original.grid_export_price_per_kwh,
            grid_export_available=original.grid_export_available,
            diesel_fuel_delivery_liters=original.diesel_fuel_delivery_liters,
            battery_power_setpoint_kw=battery_power_setpoint_kw,
            diesel_commitment_schedule=diesel_commitment_schedule,
            diesel_power_setpoint_kw=diesel_power_setpoint_kw,
        )
        dispatch = dispatch_energy_system(replay, config)
        audit = _audit(dispatch)
        summary = dispatch["summary"]
        objectives = {
            key: float(summary[key]) for key in objective_keys
        }
        results[name] = {
            "physical_audit_passed": audit["passed"],
            "audit": audit,
            "objectives": objectives,
            "service_shortfall": objectives["unmet_load_kwh"] > unmet_load_tolerance_kwh,
            "shortfall_diagnostics": diagnose_dispatch_shortfalls(dispatch, config),
            "summary": summary,
            "dispatch": dispatch,
        }

    physically_valid = all(row["physical_audit_passed"] for row in results.values())
    fully_served = all(not row["service_shortfall"] for row in results.values())
    worst_case = {
        key: max(row["objectives"][key] for row in results.values())
        for key in objective_keys
    }
    mean_case = {
        key: sum(row["objectives"][key] for row in results.values()) / len(results)
        for key in objective_keys
    }
    return {
        "scenario_count": len(results),
        "horizon_steps": horizon,
        "scenario_results": results,
        "all_physical_audits_passed": physically_valid,
        "all_scenarios_fully_served": fully_served,
        "robust_service_feasible": physically_valid and fully_served,
        "worst_case_objectives": worst_case,
        "mean_case_objectives": mean_case,
        "model_scope": {
            "same_schedule_replayed_in_every_scenario": True,
            "scenario_probabilities_assumed": False,
            "worst_case_is_not_a_probability_quantile": True,
            "uses_shared_physical_dispatch_engine": True,
            "offline_robustness_screen_only": True,
            "not_a_stochastic_or_global_robust_optimizer": True,
            "not_a_controller": True,
        },
    }
