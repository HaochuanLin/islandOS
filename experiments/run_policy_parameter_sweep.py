"""Seeded paired policy benchmark for IslandOS under no-site-data constraints.

The benchmark compares rolling dispatch, two fixed priorities, and a realized-input
reference on the exact same synthetic cases. It is a reproducible software probe,
not evidence of real-site accuracy or a proof that any policy is universally best.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean, median
from typing import Any

from experiments.rolling_horizon_dispatch import (
    generate_synthetic_scenario_csv,
    parse_scenario_csv,
    simulate_rolling,
)

POLICIES = ("rolling", "ro_first", "ice_first", "perfect_information")


def _scale(values, factor: float) -> tuple[float, ...]:
    scaled = tuple(float(value) * factor for value in values)
    if any(not math.isfinite(value) or value < 0 for value in scaled):
        raise ValueError("scaled scenario values must be finite and non-negative")
    return scaled


def build_parameter_sweep_cases(
    *, hours: int = 48, case_count: int = 20, seed: int = 20261026
) -> list[dict[str, Any]]:
    """Generate a fixed baseline plus seeded randomized stress profiles."""
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 168:
        raise ValueError("hours must be an integer from 1 to 168")
    if isinstance(case_count, bool) or not isinstance(case_count, int) or not 1 <= case_count <= 200:
        raise ValueError("case_count must be an integer from 1 to 200")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    parsed = parse_scenario_csv(generate_synthetic_scenario_csv(hours), name="parameter_sweep")
    base = parsed["scenario"]
    base_forecast = tuple(parsed["forecast_surplus_kw"])
    base_forecast_water = parsed["forecast_water_demand_m3_per_hour"]
    cases: list[dict[str, Any]] = [{
        "case_id": "baseline",
        "seed": seed,
        "factors": {
            "actual_surplus": 1.0, "forecast_surplus": 1.0,
            "water_demand": 1.0, "forecast_water_demand": 1.0, "cooling_demand": 1.0,
        },
        "scenario": base,
        "forecast_surplus": base_forecast,
        "forecast_water_demand": base_forecast_water,
    }]

    rng = random.Random(seed)
    for index in range(case_count):
        factors = {
            "actual_surplus": round(rng.uniform(0.35, 1.45), 6),
            "forecast_surplus": round(rng.uniform(0.35, 1.8), 6),
            "water_demand": round(rng.uniform(0.65, 1.9), 6),
            "forecast_water_demand": round(rng.uniform(0.65, 1.9), 6),
            "cooling_demand": round(rng.uniform(0.65, 1.9), 6),
        }
        scenario = replace(
            base,
            name=f"seeded_stress_{index + 1:03d}",
            available_surplus_kw=_scale(base.available_surplus_kw, factors["actual_surplus"]),
            water_demand_m3_per_hour=_scale(base.water_demand_m3_per_hour, factors["water_demand"]),
            cooling_demand_kw_th=_scale(base.cooling_demand_kw_th, factors["cooling_demand"]),
        )
        forecast_water = (
            _scale(base_forecast_water, factors["forecast_water_demand"])
            if base_forecast_water is not None else None
        )
        cases.append({
            "case_id": f"seeded_{index + 1:03d}",
            "seed": seed,
            "factors": factors,
            "scenario": scenario,
            "forecast_surplus": _scale(base_forecast, factors["forecast_surplus"]),
            "forecast_water_demand": forecast_water,
        })
    return cases


def _score(result: dict[str, Any], scenario) -> float:
    water_total = max(sum(scenario.water_demand_m3_per_hour), 1e-9)
    cooling_total = max(sum(scenario.cooling_demand_kw_th), 1e-9)
    power_total = max(sum(scenario.available_surplus_kw), 1e-9)
    return (
        0.45 * result["water_unmet_m3"] / water_total
        + 0.45 * result["cooling_unmet_kwh_th"] / cooling_total
        + 0.10 * result["remaining_surplus_kwh"] / power_total
    )


def run_parameter_sweep(
    *, hours: int = 48, case_count: int = 20, seed: int = 20261026
) -> dict[str, Any]:
    """Run paired policy comparisons and report aggregate plus per-case regressions."""
    cases = build_parameter_sweep_cases(hours=hours, case_count=case_count, seed=seed)
    per_case: list[dict[str, Any]] = []
    policy_scores: dict[str, list[float]] = {policy: [] for policy in POLICIES}
    policy_results: dict[str, list[dict[str, Any]]] = {policy: [] for policy in POLICIES}

    for case in cases:
        results = {}
        for policy in POLICIES:
            result = simulate_rolling(
                case["scenario"],
                case["forecast_surplus"],
                policy=policy,
                forecast_water_demand_m3_per_hour=case["forecast_water_demand"],
            )
            results[policy] = result
            policy_scores[policy].append(_score(result, case["scenario"]))
            policy_results[policy].append(result)

        fixed_best = min(("ro_first", "ice_first"), key=lambda name: (_score(results[name], case["scenario"]), name))
        scores = {name: round(_score(result, case["scenario"]), 8) for name, result in results.items()}
        rolling = results["rolling"]
        per_case.append({
            "case_id": case["case_id"],
            "scenario_name": case["scenario"].name,
            "parameter_factors": case["factors"],
            "scores": scores,
            "best_fixed_policy": fixed_best,
            "rolling_minus_best_fixed": round(scores["rolling"] - scores[fixed_best], 8),
            "rolling_water_unmet_m3": rolling["water_unmet_m3"],
            "rolling_cooling_unmet_kwh_th": rolling["cooling_unmet_kwh_th"],
            "rolling_remaining_surplus_kwh": rolling["remaining_surplus_kwh"],
            "rolling_constraint_violation_hours": rolling["constraint_violation_hours"],
            "all_policy_constraint_violation_hours": {
                name: int(result["constraint_violation_hours"]) for name, result in results.items()
            },
        })

    policy_summary = {}
    for policy, values in policy_scores.items():
        ordered = sorted(values)
        p95_index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
        policy_summary[policy] = {
            "mean_score": round(mean(values), 8),
            "median_score": round(median(values), 8),
            "p95_score": round(ordered[p95_index], 8),
            "cases_with_any_constraint_violation": sum(
                int(result["constraint_violation_hours"] > 0)
                for result in policy_results[policy]
            ),
            "mean_water_unmet_m3": round(mean(r["water_unmet_m3"] for r in policy_results[policy]), 6),
            "mean_cooling_unmet_kwh_th": round(mean(r["cooling_unmet_kwh_th"] for r in policy_results[policy]), 6),
            "mean_remaining_surplus_kwh": round(mean(r["remaining_surplus_kwh"] for r in policy_results[policy]), 6),
        }

    regressions = sorted(
        (row for row in per_case if row["rolling_minus_best_fixed"] > 1e-8),
        key=lambda row: row["rolling_minus_best_fixed"],
        reverse=True,
    )
    high_service_risk = sorted(
        per_case,
        key=lambda row: (
            row["rolling_water_unmet_m3"] + row["rolling_cooling_unmet_kwh_th"],
            row["case_id"],
        ),
        reverse=True,
    )[: min(5, len(per_case))]
    report: dict[str, Any] = {
        "report_version": 1,
        "benchmark": "seeded_paired_policy_parameter_sweep",
        "status": "synthetic_software_benchmark_not_field_validation",
        "seed": seed,
        "hours_per_case": hours,
        "randomized_case_count": case_count,
        "total_case_count": len(cases),
        "policy_names": list(POLICIES),
        "score_definition": (
            "0.45 * unmet-water / total-water-demand + "
            "0.45 * unmet-cooling / total-cooling-demand + "
            "0.10 * remaining-surplus / total-realized-surplus"
        ),
        "policy_summary": policy_summary,
        "failure_analysis": {
            "rolling_worse_than_best_fixed_case_count": len(regressions),
            "largest_rolling_regressions": regressions[:5],
            "highest_rolling_unmet_service_cases": high_service_risk,
            "interpretation": [
                "The score weights are illustrative and can change policy rankings.",
                "The realized-input reference is an offline comparison, not a deployable forecast policy or guaranteed mathematical optimum.",
                "Constraint-violation counts expose simulator events; they do not certify physical safety.",
                "All cases are synthetic scaling transforms, not sampled from a real island distribution.",
            ],
        },
        "cases": per_case,
        "all_results_simulation_only": True,
        "physical_write_performed": False,
        "live_control_enabled": False,
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=48, help="hours per case, 1–168")
    parser.add_argument("--cases", type=int, default=20, help="number of randomized cases, 1–200, plus baseline")
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--output", type=Path, default=Path("build/policy-parameter-sweep/report.json"))
    args = parser.parse_args(argv)
    try:
        report = run_parameter_sweep(hours=args.hours, case_count=args.cases, seed=args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Compared {len(report['policy_names'])} policies across {report['total_case_count']} paired synthetic cases.")
    print(f"Rolling regressions vs best fixed policy: {report['failure_analysis']['rolling_worse_than_best_fixed_case_count']}")
    print(f"Report SHA-256: {report['report_sha256']}")
    print(f"Report: {args.output}")
    print("SYNTHETIC SOFTWARE BENCHMARK ONLY — no physical equipment commands were issued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
