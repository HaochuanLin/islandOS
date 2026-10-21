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
OBJECTIVES = ("water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh")


def decode(genome: tuple) -> dict:
    return {
        "priority": genome[0],
        "ro_min_run_hours": int(genome[1]),
        "ro_start_ratio": float(genome[2]),
        "ro_rated_power_kw": float(genome[3]),
        "ice_rated_power_kw": float(genome[4]),
    }


def random_genome(rng: random.Random) -> tuple:
    return tuple(rng.choice(values) for values in GENE_VALUES)


def evaluate_genome(scenario: Scenario, genome: tuple) -> dict:
    p = decode(genome)
    ro = ROWaterLoad(ROConfig(
        rated_power_kw=p["ro_rated_power_kw"],
        specific_energy_kwh_m3=3.5,
        reservoir_capacity_m3=500.0,
        initial_water_m3=150.0,
        dead_storage_m3=20.0,
        min_run_hours=p["ro_min_run_hours"],
        start_ratio=p["ro_start_ratio"],
        allow_backup_power=False,
    ))
    ice = make_ice()
    ice.config.rated_power_kw = p["ice_rated_power_kw"]
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
    objective_values = [float(metrics[k]) for k in OBJECTIVES]
    return {
        "genome": list(genome),
        "parameters": p,
        "objectives": dict(zip(OBJECTIVES, objective_values)),
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
    for objective_index in range(len(OBJECTIVES)):
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


def crossover_mutate(a: tuple, b: tuple, rng: random.Random, mutation_rate: float) -> tuple:
    child = []
    for i, values in enumerate(GENE_VALUES):
        gene = a[i] if rng.random() < 0.5 else b[i]
        if rng.random() < mutation_rate:
            gene = rng.choice(values)
        child.append(gene)
    return tuple(child)


def optimize_scenario(
    scenario: Scenario, population_size: int = 40, generations: int = 30,
    seed: int = 20261021, mutation_rate: float = 0.2,
) -> dict:
    if population_size < 4:
        raise ValueError("population_size must be >= 4")
    if generations < 1:
        raise ValueError("generations must be >= 1")
    if not 0 <= mutation_rate <= 1:
        raise ValueError("mutation_rate must be within [0, 1]")
    rng = random.Random(seed)
    cache: dict[tuple, dict] = {}

    def evaluate(genome: tuple) -> dict:
        if genome not in cache:
            cache[genome] = evaluate_genome(scenario, genome)
        return cache[genome]

    population = [evaluate(random_genome(rng)) for _ in range(population_size)]
    for _ in range(generations):
        offspring = []
        while len(offspring) < population_size:
            parent_a = tournament(population, rng)
            parent_b = tournament(population, rng)
            genome = crossover_mutate(
                tuple(parent_a["genome"]), tuple(parent_b["genome"]), rng, mutation_rate
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
        "decision_space_size": int(np.prod([len(v) for v in GENE_VALUES])),
        "objective_directions": {key: "minimize" for key in OBJECTIVES},
        "feasible_candidate_count_evaluated": sum(row["feasible"] for row in cache.values()),
        "pareto_candidate_count": len(pareto),
        "pareto_front": pareto,
        "limitations": [
            "Optimizes a finite policy-parameter space, not arbitrary hourly setpoints.",
            "Synthetic profiles and simplified component physics only.",
            "No site-calibrated costs, uncertainty, plant interlocks, or field validation.",
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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    scenarios = [s for s in build_scenarios() if args.scenario is None or s.name == args.scenario]
    results = [optimize_scenario(
        s, args.population_size, args.generations, args.seed, args.mutation_rate
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
