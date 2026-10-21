"""NSGA-II search over IslandOS flexible-load dispatch policy parameters.

This is an experimental multi-objective evolutionary optimizer, not machine
learning. It evaluates candidates using the existing flexible-load simulator
and independent accounting audit. All bundled scenarios are synthetic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_engine import dispatch_flexible_loads
from experiments.compare_dispatch_policies import Scenario, build_scenarios, make_ice, summarize
from flexible_loads import IceStorageConfig, IceStorageLoad, ROConfig, ROWaterLoad
from islandos_config import economics_completeness, load_config
from optimization.grid_search_optimizer import audit_dispatch_result

# A mixed, finite decision space. The algorithm samples/evolves policies rather
# than claiming to optimize arbitrary minute-by-minute plant controls.
GENE_VALUES = (
    ("ro_first", "ice_first"),
    (1, 2, 3, 4),                   # RO minimum run hours
    (0.60, 0.70, 0.80, 0.90),       # RO start ratio (backup disabled)
    (250.0, 300.0, 350.0, 400.0),   # RO rated power, kW
    (50.0, 75.0, 100.0),            # chiller rated power, kW
)
BASE_OBJECTIVES = ("water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh")
COST_OBJECTIVE = "annualized_lifecycle_cost_per_year"


def decode(genome: tuple) -> dict:
    return {
        "priority": genome[0],
        "ro_min_run_hours": int(genome[1]),
        "ro_start_ratio": float(genome[2]),
        "ro_rated_power_kw": float(genome[3]),
        "ice_rated_power_kw": float(genome[4]),
    }


def random_genome(rng: random.Random, gene_values: tuple = GENE_VALUES) -> tuple:
    return tuple(rng.choice(values) for values in gene_values)


def evaluate_genome(scenario: Scenario, genome: tuple, config: dict | None = None) -> dict:
    config = config or load_config()
    p = decode(genome)
    ro_cfg = config["equipment"]["ro"]
    ice_cfg = config["equipment"]["ice"]
    ro = ROWaterLoad(ROConfig(
        rated_power_kw=p["ro_rated_power_kw"],
        specific_energy_kwh_m3=ro_cfg["specific_energy_kwh_m3"],
        reservoir_capacity_m3=ro_cfg["reservoir_capacity_m3"],
        initial_water_m3=ro_cfg["initial_water_m3"],
        dead_storage_m3=ro_cfg["dead_storage_m3"],
        min_run_hours=p["ro_min_run_hours"],
        start_ratio=p["ro_start_ratio"],
        allow_backup_power=ro_cfg["allow_backup_power"],
    ))
    ice = IceStorageLoad(IceStorageConfig(
        rated_power_kw=p["ice_rated_power_kw"],
        coefficient_of_performance=ice_cfg["coefficient_of_performance"],
        storage_capacity_kwh_th=ice_cfg["storage_capacity_kwh_th"],
        initial_storage_kwh_th=ice_cfg["initial_storage_kwh_th"],
    ))
    if p["priority"] == "ro_first":
        requests = [(ro, scenario.water_demand_m3_per_hour),
                    (ice, scenario.cooling_demand_kw_th)]
    else:
        requests = [(ice, scenario.cooling_demand_kw_th),
                    (ro, scenario.water_demand_m3_per_hour)]
    result = dispatch_flexible_loads(scenario.available_surplus_kw, requests)
    metrics = summarize("nsga2_candidate", result, scenario)
    demands = {
        "ro_desalination": np.asarray(scenario.water_demand_m3_per_hour, dtype=float),
        "ice_cold_storage": np.asarray(scenario.cooling_demand_kw_th, dtype=float),
    }
    audit = audit_dispatch_result(result, requests, demands, dt_hours=1.0)
    objective_names = list(BASE_OBJECTIVES)
    objective_values = [float(metrics[k]) for k in BASE_OBJECTIVES]
    economics_status = economics_completeness(config)
    cost_breakdown = None
    if economics_status["complete_for_current_declared_fields"]:
        economics = config["economics"]
        if len(scenario.available_surplus_kw) not in (8760, 8784):
            raise ValueError(
                "Lifecycle-cost objective requires a complete 8760-hour or 8784-hour year; "
                "short horizons cannot be annualized honestly."
            )
        if ro_cfg["allow_backup_power"]:
            raise ValueError(
                "Lifecycle-cost objective currently excludes backup-generation costs; "
                "disable backup power or add a documented backup cost model first."
            )
        energy_kwh = sum(
            float(np.sum(load.power_used_kw - load.backup_power_kw))
            for load in result.loads.values()
        )
        water_produced_m3 = float(np.sum(result.loads["ro_desalination"].resource_produced))
        rate = float(economics["discount_rate"])
        years = int(economics["analysis_years"])
        if rate == 0:
            capital_recovery_factor = 1.0 / years
        else:
            growth = (1.0 + rate) ** years
            capital_recovery_factor = rate * growth / (growth - 1.0)
        annualized_capex = (
            float(economics["ro_capex"]) + float(economics["chiller_capex"])
        ) * capital_recovery_factor
        annual_fixed_om = (
            float(economics["ro_fixed_om_per_year"])
            + float(economics["chiller_fixed_om_per_year"])
        )
        annual_variable_om = water_produced_m3 * float(economics["ro_variable_om_per_m3"])
        annual_electricity_cost = energy_kwh * float(economics["electricity_price_per_kwh"])
        annual_cost = annualized_capex + annual_fixed_om + annual_variable_om + annual_electricity_cost
        cost_breakdown = {
            "currency": economics["currency"],
            "annualized_capex": annualized_capex,
            "annual_fixed_om": annual_fixed_om,
            "annual_ro_variable_om": annual_variable_om,
            "annual_flexible_load_electricity_cost": annual_electricity_cost,
            "annualized_lifecycle_cost_per_year": annual_cost,
            "annual_energy_used_by_flexible_loads_kwh": energy_kwh,
            "annual_water_produced_m3": water_produced_m3,
            "capital_recovery_factor": capital_recovery_factor,
            "analysis_years": years,
            "discount_rate": rate,
            "accounting_note": "Assumes the supplied complete calendar-year profile is representative of each analysis year; excludes replacement schedules, taxes, financing, emissions, backup power, and unmet-service penalties.",
        }
        objective_names.append(COST_OBJECTIVE)
        objective_values.append(annual_cost)
    return {
        "genome": list(genome),
        "parameters": p,
        "objectives": dict(zip(objective_names, objective_values)),
        "objective_names": objective_names,
        "cost_breakdown": cost_breakdown,
        "objective_vector": objective_values,
        "feasible": audit["eligible_for_pareto"] is True,
        "feasibility_audit": audit,
    }


def dominates(a: dict, b: dict) -> bool:
    if a["feasible"] != b["feasible"]:
        return bool(a["feasible"])
    if not a["feasible"]:
        return False
    av, bv = a["objective_vector"], b["objective_vector"]
    return all(x <= y + 1e-9 for x, y in zip(av, bv)) and any(
        x < y - 1e-9 for x, y in zip(av, bv)
    )


def non_dominated_sort(population: list[dict]) -> list[list[dict]]:
    dominates_set: dict[int, list[int]] = {}
    dominated_count = [0] * len(population)
    fronts_idx: list[list[int]] = [[]]
    for i, a in enumerate(population):
        dominates_set[i] = []
        for j, b in enumerate(population):
            if i == j:
                continue
            if dominates(a, b):
                dominates_set[i].append(j)
            elif dominates(b, a):
                dominated_count[i] += 1
        if dominated_count[i] == 0:
            fronts_idx[0].append(i)
    front_no = 0
    while front_no < len(fronts_idx) and fronts_idx[front_no]:
        next_front = []
        for i in fronts_idx[front_no]:
            for j in dominates_set[i]:
                dominated_count[j] -= 1
                if dominated_count[j] == 0:
                    next_front.append(j)
        if next_front:
            fronts_idx.append(next_front)
        front_no += 1
    return [[population[i] for i in front] for front in fronts_idx if front]


def crowding_distance(front: list[dict]) -> dict[tuple, float]:
    distance = {tuple(row["genome"]): 0.0 for row in front}
    if len(front) <= 2:
        return {key: float("inf") for key in distance}
    objective_count = len(front[0].get("objective_names", BASE_OBJECTIVES))
    for objective_index in range(objective_count):
        ordered = sorted(front, key=lambda row: row["objective_vector"][objective_index])
        distance[tuple(ordered[0]["genome"])] = float("inf")
        distance[tuple(ordered[-1]["genome"])] = float("inf")
        low = ordered[0]["objective_vector"][objective_index]
        high = ordered[-1]["objective_vector"][objective_index]
        if high - low <= 1e-12:
            continue
        for i in range(1, len(ordered) - 1):
            key = tuple(ordered[i]["genome"])
            if np.isfinite(distance[key]):
                prev_v = ordered[i - 1]["objective_vector"][objective_index]
                next_v = ordered[i + 1]["objective_vector"][objective_index]
                distance[key] += (next_v - prev_v) / (high - low)
    return distance


def select_next_generation(population: list[dict], size: int) -> list[dict]:
    selected = []
    for front in non_dominated_sort(population):
        if len(selected) + len(front) <= size:
            selected.extend(front)
        else:
            distances = crowding_distance(front)
            front = sorted(
                front, key=lambda row: distances[tuple(row["genome"])], reverse=True
            )
            selected.extend(front[:size - len(selected)])
            break
    return selected


def tournament(population: list[dict], rng: random.Random) -> dict:
    a, b = rng.sample(population, 2)
    rank = {tuple(row["genome"]): i for i, front in enumerate(non_dominated_sort(population)) for row in front}
    ra, rb = rank[tuple(a["genome"])], rank[tuple(b["genome"])]
    if ra != rb:
        return a if ra < rb else b
    distance_map = {}
    for front in non_dominated_sort(population):
        distance_map.update(crowding_distance(front))
    da = distance_map[tuple(a["genome"])]
    db = distance_map[tuple(b["genome"])]
    if da != db:
        return a if da > db else b
    return a if rng.random() < 0.5 else b


def crossover_mutate(
    a: tuple, b: tuple, rng: random.Random, mutation_rate: float,
    gene_values: tuple = GENE_VALUES,
) -> tuple:
    child = []
    for i, values in enumerate(gene_values):
        gene = a[i] if rng.random() < 0.5 else b[i]
        if rng.random() < mutation_rate:
            gene = rng.choice(values)
        child.append(gene)
    return tuple(child)


def optimize_scenario(
    scenario: Scenario, population_size: int = 40, generations: int = 30,
    seed: int = 20261021, mutation_rate: float = 0.2,
    config: dict | None = None,
) -> dict:
    if population_size < 4:
        raise ValueError("population_size must be >= 4")
    if generations < 1:
        raise ValueError("generations must be >= 1")
    if not 0 <= mutation_rate <= 1:
        raise ValueError("mutation_rate must be within [0, 1]")
    config = config or load_config()
    economics_status = economics_completeness(config)
    if economics_status["complete_for_current_declared_fields"] and len(scenario.available_surplus_kw) not in (8760, 8784):
        raise ValueError(
            "Complete economic inputs activate lifecycle-cost optimization, which requires "
            "a complete 8760-hour or 8784-hour annual scenario."
        )
    search = config["search_space"]
    # With backup disabled, ROWaterLoad does not consult start_ratio: in
    # no-backup mode it requires rated power for every committed run hour.
    # Collapse this inactive gene to one representative value so NSGA-II does
    # not waste evaluations on phenotypically identical policies.
    start_ratio_values = (
        tuple(search["ro_start_ratio"])
        if config["equipment"]["ro"]["allow_backup_power"]
        else (search["ro_start_ratio"][0],)
    )
    gene_values = (
        tuple(search["priority"]), tuple(search["ro_min_run_hours"]),
        start_ratio_values, tuple(search["ro_rated_power_kw"]),
        tuple(search["ice_rated_power_kw"]),
    )
    rng = random.Random(seed)
    cache: dict[tuple, dict] = {}

    def evaluate(genome: tuple) -> dict:
        if genome not in cache:
            cache[genome] = evaluate_genome(scenario, genome, config)
        return cache[genome]

    population = [evaluate(random_genome(rng, gene_values)) for _ in range(population_size)]
    for _ in range(generations):
        offspring = []
        while len(offspring) < population_size:
            parent_a = tournament(population, rng)
            parent_b = tournament(population, rng)
            genome = crossover_mutate(
                tuple(parent_a["genome"]), tuple(parent_b["genome"]), rng,
                mutation_rate, gene_values,
            )
            offspring.append(evaluate(genome))
        population = select_next_generation(population + offspring, population_size)

    final_front = non_dominated_sort(population)[0]
    pareto = sorted(
        (row for row in final_front if row["feasible"]),
        key=lambda row: (row["objective_vector"], tuple(row["genome"])),
    )
    return {
        "scenario": scenario.name,
        "data_status": "synthetic illustrative scenario; not field measurements",
        "algorithm": "NSGA-II (non-dominated sorting + crowding distance + tournament selection)",
        "seed": seed,
        "population_size": population_size,
        "generations": generations,
        "unique_candidates_evaluated": len(cache),
        "decision_space_size": int(np.prod([len(v) for v in gene_values])),
        "parameter_config_name": config.get("metadata", {}).get("name", "unnamed"),
        "effective_search_space": {
            "priority": list(gene_values[0]),
            "ro_min_run_hours": list(gene_values[1]),
            "ro_start_ratio": list(gene_values[2]),
            "ro_rated_power_kw": list(gene_values[3]),
            "ice_rated_power_kw": list(gene_values[4]),
        },
        "inactive_parameters": (
            ["ro_start_ratio is collapsed to one value because backup power is disabled"]
            if not config["equipment"]["ro"]["allow_backup_power"] else []
        ),
        "objective_directions": {
            key: "minimize" for key in (
                list(BASE_OBJECTIVES) + ([COST_OBJECTIVE] if economics_status["complete_for_current_declared_fields"] else [])
            )
        },
        "cost_objective_enabled": economics_status["complete_for_current_declared_fields"],
        "cost_objective_status": (
            "enabled; see each candidate cost_breakdown"
            if economics_status["complete_for_current_declared_fields"]
            else "disabled because one or more required economic inputs are missing"
        ),
        "feasible_candidate_count_evaluated": sum(row["feasible"] for row in cache.values()),
        "pareto_candidate_count": len(pareto),
        "pareto_front": pareto,
        "limitations": [
            "Optimizes a finite policy-parameter space, not arbitrary hourly setpoints.",
            "Synthetic profiles and simplified component physics only.",
            "Lifecycle cost is enabled only with complete cost inputs and a complete annual profile; omitted replacement schedules, taxes, financing, emissions, backup, and unmet-service penalties.",
            "No plant interlocks or field validation.",
            "Pareto solutions expose trade-offs; they do not identify a universally best policy.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[s.name for s in build_scenarios()])
    parser.add_argument("--population-size", type=int, default=40)
    parser.add_argument("--generations", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--mutation-rate", type=float, default=0.2)
    parser.add_argument("--config", help="JSON parameter configuration; defaults are explicitly illustrative")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    scenarios = [s for s in build_scenarios() if args.scenario is None or s.name == args.scenario]
    results = [optimize_scenario(
        s, args.population_size, args.generations, args.seed, args.mutation_rate, config
    ) for s in scenarios]
    if args.json:
        print(json.dumps(results, indent=2))
        return
    print("IslandOS NSGA-II policy-parameter search — synthetic scenarios only")
    for result in results:
        print(f"{result['scenario']}: evaluated={result['unique_candidates_evaluated']}/"
              f"{result['decision_space_size']}, feasible="
              f"{result['feasible_candidate_count_evaluated']}, "
              f"Pareto={result['pareto_candidate_count']}")
        for row in result["pareto_front"]:
            print(f"  {row['parameters']} -> {row['objectives']}")


if __name__ == "__main__":
    main()
