"""Head-to-head benchmark: evolutionary search versus the MILP on identical inputs.

Every method is scored on the same replayed physics (``dispatch_energy_system``)
and the same synthetic island inputs from ``islandos_core.impact_scenario``.
The RO plant follows the fixed timetable in every run, so this benchmark is
about battery, diesel and grid scheduling only; joint water timing is covered
by ``run_optimizer_impact.py``.

Cases:
  island      off-grid, diesel only
  hybrid_tou  30 kW grid on a time-of-use tariff plus diesel with a start cost
  grid_tou    80 kW grid on the same tariff, diesel unavailable

Diesel variants:
  plain        no ramp-down or minimum run times
  constrained  ramp-down 10 kW/h, minimum up time 3 h, minimum down time 3 h

All inputs are synthetic. The results compare algorithms; they are not
measured savings at any real site.

    python experiments/run_optimizer_benchmark.py --input-seeds 3 --ea-seeds 3
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_core.energy_system import dispatch_energy_system  # noqa: E402
from islandos_core.impact_scenario import (  # noqa: E402
    IslandSiteConfig, StrategyRules, _energy_inputs, energy_system_setup,
    generate_synthetic_inputs, run_strategy,
)
from optimization.energy_system_optimizer import (  # noqa: E402
    OptimizationError, optimize_battery_and_diesel_schedule,
)
from optimization.milp_dispatch_optimizer import optimize_dispatch_milp  # noqa: E402

UNMET_TOLERANCE_KWH = 0.01
CONSTRAINED_DIESEL = {"ramp_down_kw_per_hour": 10.0, "min_up_time_hours": 3.0, "min_down_time_hours": 3.0}


def build_case(case: str, variant: str, days: int, input_seed: int, site: IslandSiteConfig):
    inputs = generate_synthetic_inputs(site, days=days, seed=input_seed)
    config, _ = energy_system_setup(site, case)
    if variant == "constrained" and config.diesel is not None:
        config = replace(config, diesel=replace(config.diesel, **CONSTRAINED_DIESEL))
    ro_kw = run_strategy("baseline", inputs, site, StrategyRules()).hourly["ro_power_kw"]
    return _energy_inputs(inputs, case, ro_kw), config


def run_rule(energy_inputs, config) -> dict:
    started = time.perf_counter()
    summary = dispatch_energy_system(energy_inputs, config, policy="battery_first")["summary"]
    return {
        "cost": float(summary["estimated_energy_cost"]),
        "unmet_kwh": float(summary["unmet_load_kwh"]),
        "runtime_s": time.perf_counter() - started,
        "status": "rule",
    }


def run_milp(energy_inputs, config, time_limit_seconds: float) -> dict:
    started = time.perf_counter()
    try:
        result = optimize_dispatch_milp(energy_inputs, config, time_limit_seconds=time_limit_seconds)
    except OptimizationError as exc:
        return {"cost": None, "unmet_kwh": None, "runtime_s": time.perf_counter() - started,
                "status": f"error: {exc}"}
    summary = result["dispatch"]["summary"]
    return {
        "cost": float(summary["estimated_energy_cost"]),
        "unmet_kwh": float(summary["unmet_load_kwh"]),
        "runtime_s": time.perf_counter() - started,
        "status": "optimal" if result["optimality_proven_for_declared_milp"] else f"solver_status_{result['solver_status']}",
    }


def run_evolutionary(energy_inputs, config, seed: int, warm: bool, population: int, generations: int) -> dict:
    started = time.perf_counter()
    try:
        result = optimize_battery_and_diesel_schedule(
            energy_inputs, config, seed=seed, population_size=population, generations=generations,
            max_unmet_load_kwh=UNMET_TOLERANCE_KWH, warm_start_from_rule_dispatch=warm,
        )
    except OptimizationError as exc:
        return {"cost": None, "unmet_kwh": None, "runtime_s": time.perf_counter() - started,
                "status": f"no feasible schedule: {str(exc)[:120]}"}
    # The search is multi-objective and recommends a weighted compromise. For a
    # cost comparison with the MILP, score it by the cheapest feasible schedule
    # on its Pareto front, and record the recommended schedule's cost as well.
    cheapest = min(result["pareto_schedules"], key=lambda row: row["objectives"]["estimated_energy_cost"])
    objectives = cheapest["objectives"]
    return {
        "cost": float(objectives["estimated_energy_cost"]),
        "unmet_kwh": float(objectives["unmet_load_kwh"]),
        "recommended_cost": float(result["recommendation"]["objectives"]["estimated_energy_cost"]),
        "runtime_s": time.perf_counter() - started,
        "status": "feasible",
        "feasible_candidates": result["feasible_count"],
        "candidates": result["candidate_count"],
    }


def run_task(task: tuple) -> list[dict]:
    """All methods on one (case, diesel variant, horizon, input seed)."""
    case, variant, horizon, input_seed, ea_seeds, population, generations, time_limit = task
    site = IslandSiteConfig()
    energy_inputs, config = build_case(case, variant, horizon // 24, input_seed, site)
    base = {"case": case, "variant": variant, "horizon_h": horizon, "input_seed": input_seed}
    milp = run_milp(energy_inputs, config, time_limit)
    results = [("rule", None, run_rule(energy_inputs, config)), ("milp", None, milp)]
    for ea_seed in range(1, ea_seeds + 1):
        for method, warm in (("ea_cold", False), ("ea_warm", True)):
            results.append((method, ea_seed, run_evolutionary(
                energy_inputs, config, ea_seed, warm, population, generations)))
    rows = []
    for method, ea_seed, res in results:
        gap = None
        if res["cost"] is not None and milp["cost"] is not None:
            gap = (res["cost"] - milp["cost"]) / max(milp["cost"], 1e-9) * 100
        rows.append({**base, "method": method, "ea_seed": ea_seed, **res, "gap_vs_milp_pct": gap})
    print(f"{case:10s} {variant:11s} {horizon:3d}h seed {input_seed}: MILP {milp['cost']} ({milp['status']})", flush=True)
    return rows


def summarise(rows: list[dict]) -> list[dict]:
    """Aggregate per (case, variant, horizon, method): mean gap to the MILP,
    worst gap, failures, runtime, and spread across evolutionary seeds."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row["case"], row["variant"], row["horizon_h"], row["method"]), []).append(row)
    out = []
    method_order = {"rule": 0, "milp": 1, "ea_cold": 2, "ea_warm": 3}
    case_order = {"island": 0, "hybrid_tou": 1, "grid_tou": 2}
    ordered = sorted(groups.items(), key=lambda kv: (
        case_order[kv[0][0]], kv[0][1] != "plain", kv[0][2], method_order[kv[0][3]]))
    for (case, variant, horizon, method), items in ordered:
        gaps = [r["gap_vs_milp_pct"] for r in items if r["gap_vs_milp_pct"] is not None]
        spreads = []
        by_input: dict[int, list[float]] = {}
        for r in items:
            if r["cost"] is not None:
                by_input.setdefault(r["input_seed"], []).append(r["cost"])
        for costs in by_input.values():
            if len(costs) > 1:
                spreads.append((max(costs) - min(costs)) / max(min(costs), 1e-9) * 100)
        out.append({
            "case": case, "variant": variant, "horizon_h": horizon, "method": method,
            "runs": len(items),
            "failed_runs": sum(r["cost"] is None for r in items),
            "mean_gap_vs_milp_pct": round(statistics.mean(gaps), 3) if gaps else None,
            "worst_gap_vs_milp_pct": round(max(gaps), 3) if gaps else None,
            "runs_matching_milp_within_0_1pct": sum(g <= 0.1 for g in gaps),
            "mean_runtime_s": round(statistics.mean(r["runtime_s"] for r in items), 3),
            "max_seed_spread_pct": round(max(spreads), 3) if spreads else None,
        })
    return out


def timeout_probe(site: IslandSiteConfig) -> dict:
    """Solve the 7-day joint water-energy MILP with a tiny time limit and record
    what the solver reports. The pipeline must never claim optimality here."""
    inputs = generate_synthetic_inputs(site, days=7, seed=0)
    config, water = energy_system_setup(site, "grid_tou")
    started = time.perf_counter()
    try:
        result = optimize_dispatch_milp(
            _energy_inputs(inputs, "grid_tou"), config, water_service=water,
            water_demand_m3_per_hour=[float(x) for x in inputs.water_demand_m3],
            terminal_water_inventory_min_m3=site.tank_initial_m3,
            ro_min_production_m3_per_hour=site.ro_min_power_kw / site.ro_specific_energy_kwh_per_m3,
            time_limit_seconds=0.05,
        )
        outcome = {
            "raised": False,
            "solver_status": result["solver_status"],
            "optimality_proven": result["optimality_proven_for_declared_milp"],
            "mip_gap": result["mip_gap"],
        }
    except OptimizationError as exc:
        outcome = {"raised": True, "message": str(exc)[:200], "optimality_proven": False}
    outcome["runtime_s"] = round(time.perf_counter() - started, 3)
    return outcome


LABELS = {"rule": "Rule dispatch (battery first)", "milp": "MILP (HiGHS)",
          "ea_cold": "Evolutionary, random start", "ea_warm": "Evolutionary, warm start"}


def write_summary_md(path: Path, aggregate: list[dict], probe: dict, args) -> None:
    lines = [
        "# Optimizer benchmark (synthetic inputs)",
        "",
        f"Input seeds: {args.input_seeds}. Evolutionary seeds per input: {args.ea_seeds}. "
        f"Evolutionary budget: population {args.population}, {args.generations} generations. "
        f"Evolutionary runs must keep unmet load at or below {UNMET_TOLERANCE_KWH} kWh.",
        "",
        "Gap is the energy cost of a method minus the MILP cost on the same inputs, as a percentage of the MILP cost. "
        "The evolutionary search is scored by the cheapest feasible schedule on its Pareto front. "
        "Seed spread is the largest cost range across evolutionary seeds on one input.",
        "",
        "| Case | Diesel | Horizon | Method | Runs | Failed | Mean gap | Worst gap | Matches MILP | Mean runtime (s) | Seed spread |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in aggregate:
        def fmt(v, suffix=""):
            return "n/a" if v is None else f"{v}{suffix}"
        lines.append(
            f"| {row['case']} | {row['variant']} | {row['horizon_h']} h | {LABELS[row['method']]} | {row['runs']} | "
            f"{row['failed_runs']} | {fmt(row['mean_gap_vs_milp_pct'], '%')} | {fmt(row['worst_gap_vs_milp_pct'], '%')} | "
            f"{row['runs_matching_milp_within_0_1pct']} | {row['mean_runtime_s']} | {fmt(row['max_seed_spread_pct'], '%')} |"
        )
    lines += [
        "",
        "On grid_tou the diesel unit is unavailable, so only the plain diesel variant is run there.",
        "",
        "## Solver timeout probe",
        "",
        "7-day joint water-energy MILP on grid_tou with a 0.05 s time limit:",
        "",
        "```",
        json.dumps(probe, indent=2),
        "```",
        "",
        "The run either stops with a clear error or returns a schedule marked as not proven optimal.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input-seeds", type=int, default=3)
    parser.add_argument("--ea-seeds", type=int, default=3)
    parser.add_argument("--horizons", type=int, nargs="+", default=[24, 168])
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--generations", type=int, default=60)
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=1, help="parallel worker processes")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "optimizer_benchmark")
    args = parser.parse_args(argv)
    if any(h % 24 or not 24 <= h <= 168 for h in args.horizons):
        parser.error("horizons must be whole days between 24 and 168 hours")

    site = IslandSiteConfig()
    tasks = []
    for case in ("island", "hybrid_tou", "grid_tou"):
        variants = ("plain",) if case == "grid_tou" else ("plain", "constrained")
        for variant in variants:
            for horizon in args.horizons:
                for input_seed in range(args.input_seeds):
                    tasks.append((case, variant, horizon, input_seed, args.ea_seeds, args.population,
                                  args.generations, args.time_limit))
    if args.workers > 1:
        from multiprocessing import Pool
        with Pool(args.workers) as pool:
            results = pool.map(run_task, tasks)
    else:
        results = [run_task(task) for task in tasks]
    rows = [row for chunk in results for row in chunk]

    aggregate = summarise(rows)
    probe = timeout_probe(site)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = ["case", "variant", "horizon_h", "input_seed", "method", "ea_seed", "cost", "unmet_kwh",
              "gap_vs_milp_pct", "recommended_cost", "runtime_s", "status", "feasible_candidates", "candidates"]
    with (args.output_dir / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "aggregate.json").write_text(
        json.dumps({"aggregate": aggregate, "timeout_probe": probe,
                    "settings": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
                    "constrained_diesel": CONSTRAINED_DIESEL, "synthetic": True}, indent=2),
        encoding="utf-8")
    write_summary_md(args.output_dir / "summary.md", aggregate, probe, args)
    print((args.output_dir / "summary.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
