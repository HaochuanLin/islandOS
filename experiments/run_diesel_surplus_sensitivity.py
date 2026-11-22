"""Controlled sensitivity study for diesel displacement from flexible RO scheduling.

All scenarios are synthetic design cases, not calibrated sites or forecasts.
Run from the repository root:
    python experiments/run_diesel_surplus_sensitivity.py --seeds 10 --days 3
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_core.impact_scenario import (  # noqa: E402
    IslandSiteConfig, StrategyRules, compare_with_optimizer, generate_synthetic_inputs,
)

SCENARIOS = {
    "A_baseline": {"pv_rated_kw": 60.0, "wind_rated_kw": 40.0, "tank_capacity_m3": 80.0},
    "B_more_wind": {"pv_rated_kw": 60.0, "wind_rated_kw": 70.0, "tank_capacity_m3": 80.0},
    "C_larger_tank": {"pv_rated_kw": 60.0, "wind_rated_kw": 40.0, "tank_capacity_m3": 120.0},
    "D_wind_and_tank": {"pv_rated_kw": 60.0, "wind_rated_kw": 70.0, "tank_capacity_m3": 120.0},
}
STRATEGIES = ("fixed_timetable", "surplus_rule", "forecast_rule",
              "forecast_rule_realistic", "joint_milp", "joint_milp_with_reserve")


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "results" / "diesel_surplus_sensitivity")
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be >= 1")
    if not 1 <= args.days <= 7:
        parser.error("--days must be between 1 and 7 (MILP limit: 168 hours)")

    base = IslandSiteConfig()
    rules = StrategyRules()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for scenario, overrides in SCENARIOS.items():
        site = replace(base, **overrides)
        for seed in range(args.seeds):
            inputs = generate_synthetic_inputs(site, days=args.days, seed=seed)
            result = compare_with_optimizer(inputs, site, rules, case="island")
            by_name = {row["strategy"]: row for row in result["strategies"]}
            for strategy in STRATEGIES:
                item = by_name[strategy]
                record = {
                    "scenario": scenario, "seed": seed, "input_sha256": result["input_sha256"],
                    "strategy": strategy,
                    "diesel_litres_tank_adjusted": item.get("diesel_litres_tank_adjusted"),
                    "diesel_litres_raw": item.get("diesel_litres"),
                    "diesel_generation_kwh": item["diesel_kwh"],
                    "renewable_curtailed_kwh": item.get("renewable_curtailed_kwh"),
                    "ending_tank_m3": item["ending_tank_m3"],
                    "unmet_water_m3": item["unmet_water_m3"],
                    "unmet_electric_kwh": item["unmet_electric_kwh"],
                    "optimality_proven": item.get("optimality_proven"),
                    "solver_status": item.get("solver_status"),
                }
                rows.append(record)
                grouped[scenario][strategy].append(float(item["headline_tank_adjusted"]))

    csv_path = args.output_dir / "per_seed_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = {}
    for scenario, strategies in grouped.items():
        baseline = np.asarray(strategies["fixed_timetable"], dtype=float)
        summary[scenario] = {}
        for strategy, values in strategies.items():
            arr = np.asarray(values, dtype=float)
            pct = 100.0 * (arr - baseline) / np.maximum(baseline, 1e-9)
            summary[scenario][strategy] = {
                "mean_tank_adjusted_diesel_litres": float(arr.mean()),
                "mean_change_vs_fixed_pct": float(pct.mean()),
                "min_change_vs_fixed_pct": float(pct.min()),
                "max_change_vs_fixed_pct": float(pct.max()),
                "seeds_better_than_fixed": int(np.sum(arr < baseline - 1e-8)),
            }
    payload = {
        "description": "Synthetic scenario sensitivity; not site data or validated fuel savings.",
        "metric": "tank-adjusted diesel litres using the repository's constant litres_per_kWh assumption",
        "seeds": list(range(args.seeds)), "days": args.days,
        "scenario_overrides": SCENARIOS, "base_site_assumptions": asdict(base),
        "git_commit": git_commit(), "python": platform.python_version(),
        "numpy": np.__version__, "summary": summary,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["# Diesel surplus sensitivity", "",
             "All results are synthetic model outputs, not measurements or customer savings.", "",
             "Fuel litres use the model's constant litres/kWh conversion; no nonlinear generator fuel curve is represented.", "",
             "| Scenario | Strategy | Mean tank-adjusted L | Change vs fixed | Range | Seeds better than fixed |",
             "|---|---|---:|---:|---:|---:|"]
    for scenario, strategies in summary.items():
        for strategy, values in strategies.items():
            lines.append(
                f"| {scenario} | {strategy} | {values['mean_tank_adjusted_diesel_litres']:.2f} | "
                f"{values['mean_change_vs_fixed_pct']:+.2f}% | "
                f"{values['min_change_vs_fixed_pct']:+.2f}% to {values['max_change_vs_fixed_pct']:+.2f}% | "
                f"{values['seeds_better_than_fixed']}/{args.seeds} |"
            )
    lines += ["", "## Interpretation guardrails", "",
              "- Compare joint MILP against both fixed timetable and surplus rule; the latter is the stronger operational baseline.",
              "- Check water shortage, unmet essential electricity, and terminal tank inventory in per_seed_results.csv.",
              "- Do not describe constant-rate litres as validated real-generator fuel savings.",
              "- The scenario overrides are sensitivity assumptions, not claims about a real island."]
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "command": "python experiments/run_diesel_surplus_sensitivity.py " +
                   " ".join(argv if argv is not None else sys.argv[1:]),
        "git_commit": git_commit(), "seeds": list(range(args.seeds)), "days": args.days,
        "scenario_overrides": SCENARIOS, "output_files": ["per_seed_results.csv", "summary.json", "summary.md"],
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    main()
