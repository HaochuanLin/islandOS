"""Compare NSGA-II against an exact exhaustive Pareto reference.

This is an evaluation aid, not a claim that either search method improves the
underlying simulator. Exact search is practical only while the configured
finite decision space remains manageable.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_dispatch_policies import build_scenarios
from islandos_config import load_config
from optimization.nsga2_dispatch_optimizer import (
    evaluate_genome, non_dominated_sort, optimize_scenario,
)


def effective_gene_values(config: dict) -> tuple[tuple, ...]:
    """Mirror the optimizer's effective gene space, removing inactive ratio genes."""
    search = config["search_space"]
    ratio = (
        tuple(search["ro_start_ratio"])
        if config["equipment"]["ro"]["allow_backup_power"]
        else (search["ro_start_ratio"][0],)
    )
    return (
        tuple(search["priority"]),
        tuple(search["ro_min_run_hours"]),
        ratio,
        tuple(search["ro_rated_power_kw"]),
        tuple(search["ice_rated_power_kw"]),
    )


def exhaustive_pareto(scenario, config: dict, max_candidates: int = 100_000) -> dict:
    """Evaluate every configured genome and return the exact feasible Pareto front."""
    gene_values = effective_gene_values(config)
    space_size = 1
    for values in gene_values:
        space_size *= len(values)
    if space_size > max_candidates:
        raise ValueError(
            f"Exhaustive search would evaluate {space_size} candidates, above "
            f"the safety limit {max_candidates}; raise --max-candidates explicitly."
        )
    start = time.perf_counter()
    candidates = [
        evaluate_genome(scenario, genome, config)
        for genome in itertools.product(*gene_values)
    ]
    fronts = non_dominated_sort(candidates)
    front = sorted(
        (row for row in (fronts[0] if fronts else []) if row["feasible"]),
        key=lambda row: (row["objective_vector"], tuple(row["genome"])),
    )
    return {
        "decision_space_size": space_size,
        "unique_candidates_evaluated": len(candidates),
        "feasible_candidate_count_evaluated": sum(row["feasible"] for row in candidates),
        "pareto_front": front,
        "elapsed_seconds": time.perf_counter() - start,
    }


def benchmark(scenario, config: dict, population_size: int = 40,
              generations: int = 30, seed: int = 20261021,
              max_candidates: int = 100_000) -> dict:
    exact = exhaustive_pareto(scenario, config, max_candidates=max_candidates)
    evolutionary = optimize_scenario(
        scenario, population_size=population_size, generations=generations,
        seed=seed, config=config,
    )
    exact_keys = {tuple(row["genome"]) for row in exact["pareto_front"]}
    nsga_keys = {tuple(row["genome"]) for row in evolutionary["pareto_front"]}
    overlap = exact_keys & nsga_keys
    recall = len(overlap) / len(exact_keys) if exact_keys else 1.0
    precision = len(overlap) / len(nsga_keys) if nsga_keys else (1.0 if not exact_keys else 0.0)
    return {
        "scenario": scenario.name,
        "data_status": "synthetic illustrative scenario; not field measurements",
        "seed": seed,
        "population_size": population_size,
        "generations": generations,
        "decision_space_size": exact["decision_space_size"],
        "exact": {
            "unique_candidates_evaluated": exact["unique_candidates_evaluated"],
            "feasible_candidate_count_evaluated": exact["feasible_candidate_count_evaluated"],
            "pareto_front_count": len(exact_keys),
            "elapsed_seconds": exact["elapsed_seconds"],
            "pareto_genomes": [list(key) for key in sorted(exact_keys, key=repr)],
        },
        "nsga2": {
            "unique_candidates_evaluated": evolutionary["unique_candidates_evaluated"],
            "feasible_candidate_count_evaluated": evolutionary["feasible_candidate_count_evaluated"],
            "pareto_front_count": len(nsga_keys),
            "pareto_genomes": [list(key) for key in sorted(nsga_keys, key=repr)],
        },
        "comparison": {
            "overlap_count": len(overlap),
            "exact_front_recall": recall,
            "nsga2_front_precision": precision,
            "exact_front_missed_genomes": [list(key) for key in sorted(exact_keys - nsga_keys, key=repr)],
            "nsga2_genomes_not_in_exact_front": [list(key) for key in sorted(nsga_keys - exact_keys, key=repr)],
            "interpretation": (
                "Exact exhaustive Pareto front is the reference for this finite configured space. "
                "Recall/precision compare genome identity, not generalization to unseen conditions."
            ),
        },
        "limitations": [
            "Both methods use the same simplified simulator and feasibility audit.",
            "This benchmark measures search coverage, not physical accuracy or real-site performance.",
            "Exact search time is machine-dependent; do not compare timings across unlike environments.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[s.name for s in build_scenarios()])
    parser.add_argument("--population-size", type=int, default=40)
    parser.add_argument("--generations", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--config", help="JSON parameter configuration")
    parser.add_argument("--max-candidates", type=int, default=100_000)
    parser.add_argument("--output", help="Optional path to write JSON results")
    args = parser.parse_args()
    config = load_config(args.config)
    scenarios = [s for s in build_scenarios() if args.scenario is None or s.name == args.scenario]
    results = [
        benchmark(s, config, args.population_size, args.generations, args.seed, args.max_candidates)
        for s in scenarios
    ]
    output = json.dumps(results, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
