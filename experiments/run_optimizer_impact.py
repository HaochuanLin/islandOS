"""Compare rule strategies with the joint water-energy MILP over many synthetic weeks.

Example:
    python experiments/run_optimizer_impact.py --seeds 30 --output-dir results/optimizer_impact

Two cases are run on identical synthetic weeks:
    island    off-grid with diesel backup; headline = tank-adjusted diesel litres
    grid_tou  80 kW grid with a time-of-use tariff, no diesel; headline = tank-adjusted cost

All inputs are synthetic. The results describe the model, not a real site.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_core.impact_scenario import (  # noqa: E402
    CASES, IslandSiteConfig, StrategyRules, TOU_PRICES, assumptions_record,
    compare_with_optimizer, flexible_load_study, generate_synthetic_inputs,
)

LABELS = {
    "fixed_timetable": "Fixed RO timetable (07:00 to 19:00)",
    "surplus_rule": "Simple surplus rule",
    "forecast_rule": "Forecast-based rule (perfect forecast)",
    "forecast_rule_realistic": "Forecast-based rule (20% forecast error, 3 h minimum run)",
    "just_in_time": "Just-in-time RO",
    "tariff_lookahead": "Tariff look-ahead RO",
    "milp_battery_only_fixed_ro": "Optimised battery, fixed RO timetable",
    "joint_milp": "Joint water-energy optimisation (MILP)",
    "joint_milp_with_reserve": "Joint optimisation keeping a 20 m3 tank reserve",
}


def git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return head.stdout.strip() + ("+uncommitted-changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def summarise(runs: list[dict]) -> dict:
    by_strategy: dict[str, list[float]] = {}
    unmet_water: dict[str, float] = {}
    for run in runs:
        for row in run["strategies"]:
            by_strategy.setdefault(row["strategy"], []).append(row["headline_tank_adjusted"])
            unmet_water[row["strategy"]] = unmet_water.get(row["strategy"], 0.0) + row["unmet_water_m3"]
    base = np.asarray(by_strategy["fixed_timetable"])
    out = {}
    for name, values in by_strategy.items():
        arr = np.asarray(values)
        change = 100.0 * (arr - base) / base
        out[name] = {
            "mean": float(arr.mean()),
            "mean_change_vs_fixed_pct": float(change.mean()),
            "min_change_vs_fixed_pct": float(change.min()),
            "max_change_vs_fixed_pct": float(change.max()),
            "weeks_better_than_fixed": int((arr < base - 1e-9).sum()),
            "unmet_water_m3_total": float(unmet_water[name]),
        }
    statuses = [row.get("solver_status") for run in runs for row in run["strategies"] if row["strategy"] == "joint_milp"]
    out["_joint_milp_all_optimal"] = all(status == 0 for status in statuses)
    return out


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build" / "optimizer-impact")
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be at least 1")
    if not 1 <= args.days <= 7:
        parser.error("--days must be between 1 and 7 (the MILP accepts at most 168 hours)")

    site, rules = IslandSiteConfig(), StrategyRules()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    with open(out / "per_seed.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case", "seed", "input_sha256", "strategy", "headline_tank_adjusted",
                         "energy_cost", "diesel_kwh", "grid_kwh", "ending_tank_m3", "unmet_electric_kwh",
                         "unmet_water_m3"])
        for case in CASES:
            runs = []
            for seed in range(args.seeds):
                run = compare_with_optimizer(generate_synthetic_inputs(site, days=args.days, seed=seed), site, rules, case=case)
                runs.append(run)
                for row in run["strategies"]:
                    writer.writerow([case, seed, run["input_sha256"], row["strategy"],
                                     round(row["headline_tank_adjusted"], 4), round(row["energy_cost"], 4),
                                     round(row["diesel_kwh"], 4), round(row["grid_kwh"], 4),
                                     round(row["ending_tank_m3"], 4), round(row["unmet_electric_kwh"], 6),
                                     round(row["unmet_water_m3"], 4)])
            results[case] = summarise(runs)
    results["flexible_load"] = flexible_summary(site, args.seeds)
    (out / "aggregate.json").write_text(json.dumps(results, indent=2))
    manifest = {
        "description": "Rule strategies vs joint water-energy MILP on synthetic weeks. Not site data.",
        "git_commit": git_commit(),
        "command": "python experiments/run_optimizer_impact.py " + " ".join(argv if argv is not None else sys.argv[1:]),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "seeds": list(range(args.seeds)),
        "days": args.days,
        "tou_prices_usd_per_kwh": TOU_PRICES,
        "assumptions": json.loads(assumptions_record(site, rules)),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    write_markdown(out / "summary.md", results, args)
    return results


FLEX_WINDOWS = {"daytime_06_22": (6, 22), "any_hour": (0, 24)}
FLEX_LABELS = {
    "rule_dispatch_early_flexible_load": "Rule dispatch, load run as early as allowed",
    "milp_battery_only_early_flexible_load": "Optimised battery, load still run early",
    "milp_joint_flexible_load": "Optimised battery and load timing",
}


def flexible_summary(site: IslandSiteConfig, seeds: int) -> dict:
    """One synthetic day per seed: 40 kWh of flexible load, at most 10 kW."""
    out = {}
    for case in ("island", "grid_tou"):
        for window_name, window in FLEX_WINDOWS.items():
            costs: dict[str, list[float]] = {}
            for seed in range(seeds):
                study = flexible_load_study(generate_synthetic_inputs(site, days=1, seed=seed), site,
                                            case=case, window=window)
                for row in study["strategies"]:
                    costs.setdefault(row["strategy"], []).append(row["energy_cost"])
            base = np.asarray(costs["rule_dispatch_early_flexible_load"])
            out[f"{case}/{window_name}"] = {
                name: {"mean_energy_cost": float(np.mean(values)),
                       "change_in_mean_cost_vs_rule_pct": float(100.0 * (np.mean(values) - base.mean()) / base.mean()),
                       "days_better_than_rule": int((np.asarray(values) < base - 1e-9).sum())}
                for name, values in costs.items()
            }
    return out


def write_markdown(path: Path, results: dict, args) -> None:
    lines = [f"# Rule strategies vs joint optimisation ({args.seeds} synthetic weeks)", ""]
    units = {"island": "diesel litres per week, adjusted for water left in the tank",
             "grid_tou": "energy cost (USD) per week, adjusted for water left in the tank",
             "hybrid_tou": "energy cost (USD) per week including diesel starts, adjusted for water left in the tank"}
    for case in CASES:
        lines += [f"## {case}", "", f"Headline: {units[case]}.", "",
                  "| Strategy | Mean | Change vs fixed timetable | Range across weeks | Weeks better | Water shortage (m3, all weeks) |",
                  "|---|---|---|---|---|---|"]
        for name, label in LABELS.items():
            row = results[case].get(name)
            if row is None:
                continue
            lines.append(f"| {label} | {row['mean']:.1f} | {row['mean_change_vs_fixed_pct']:+.1f}% | "
                         f"{row['min_change_vs_fixed_pct']:+.1f}% to {row['max_change_vs_fixed_pct']:+.1f}% | "
                         f"{row['weeks_better_than_fixed']}/{args.seeds} | {row['unmet_water_m3_total']:.1f} |")
        lines += ["", f"Every joint MILP solve proven optimal: {results[case]['_joint_milp_all_optimal']}.", ""]
    lines += ["## Flexible load timing", "",
              f"One synthetic day per seed ({args.seeds} days). A 40 kWh flexible load (at most 10 kW) must run inside "
              "its window; RO stays on the fixed timetable. Energy cost in USD per day.", "",
              "| Case | Window | Strategy | Mean cost | Change in mean cost vs rule dispatch | Days better |",
              "|---|---|---|---|---|---|"]
    for key, rows in results["flexible_load"].items():
        case, window = key.split("/")
        for name, label in FLEX_LABELS.items():
            row = rows[name]
            lines.append(f"| {case} | {window} | {label} | {row['mean_energy_cost']:.2f} | "
                         f"{row['change_in_mean_cost_vs_rule_pct']:+.1f}% | {row['days_better_than_rule']}/{args.seeds} |")
    lines.append("")
    lines.append("All numbers are simulation results on synthetic inputs, not measurements.")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
