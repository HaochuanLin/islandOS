"""Run the synthetic baseline-versus-coordinated impact scenario over many seeds.

Example:
    python experiments/run_impact_scenario.py --seeds 30 --days 7 --output-dir build/impact-scenario

Writes, for full reproducibility:
    manifest.json          git commit, versions, assumptions, seeds and input hashes
    per_seed_summary.csv   one row per seed and strategy
    aggregate.json         mean, min and max of each metric and of the difference
    hourly_seed0.csv       hour-by-hour audit for seed 0, both strategies
    summary.md             a short table that can be pasted into the proposal
    impact_seed0.png       chart of seed 0 (only if matplotlib is installed)

All inputs are synthetic. The results describe the model, not a real island.
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
    IslandSiteConfig, StrategyRules, assumptions_record, compare, generate_synthetic_inputs,
)

HEADLINE = [
    ("diesel_litres_tank_adjusted", "Diesel, adjusted for water left in tank (litres)"),
    ("co2_kg_tank_adjusted", "CO2, adjusted for water left in tank (kg)"),
    ("diesel_litres", "Diesel used, unadjusted (litres)"),
    ("co2_kg", "CO2 from diesel, unadjusted (kg)"),
    ("diesel_cost", "Diesel cost (USD)"),
    ("diesel_hours", "Generator running hours"),
    ("renewable_curtailed_kwh", "Renewable energy curtailed (kWh)"),
    ("renewable_used_pct", "Renewable energy used (%)"),
    ("water_service_pct", "Water demand served (%)"),
    ("water_litres_per_household_per_day", "Water served per household per day (litres)"),
    ("brine_m3", "Brine discharged (m3, rough estimate)"),
    ("unserved_essential_kwh", "Essential load not served (kWh)"),
    ("ro_starts", "RO start-ups"),
    ("final_tank_m3", "Water in tank at end (m3)"),
]


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + ("+uncommitted-changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def stats(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {"mean": float(arr.mean()), "min": float(arr.min()), "max": float(arr.max())}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, default=30, help="number of random seeds (0..N-1)")
    parser.add_argument("--days", type=int, default=7, help="days simulated per seed")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build" / "impact-scenario")
    parser.add_argument("--sensitivity", action="store_true", help="also vary key assumptions and write sensitivity.csv")
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be at least 1")

    site, rules = IslandSiteConfig(), StrategyRules()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    runs = [compare(generate_synthetic_inputs(site, days=args.days, seed=s), site, rules) for s in range(args.seeds)]

    with open(out / "per_seed_summary.csv", "w", newline="") as f:
        keys = list(runs[0]["baseline"].summary)
        writer = csv.writer(f)
        writer.writerow(["seed", "input_sha256", "strategy", *keys])
        for r in runs:
            for name in ("baseline", "coordinated"):
                writer.writerow([r["seed"], r["input_sha256"], name, *(round(r[name].summary[k], 4) for k in keys)])

    aggregate = {"baseline": {}, "coordinated": {}, "difference": {}, "relative_change_pct": {}}
    for key, _ in HEADLINE:
        b = [r["baseline"].summary[key] for r in runs]
        c = [r["coordinated"].summary[key] for r in runs]
        aggregate["baseline"][key] = stats(b)
        aggregate["coordinated"][key] = stats(c)
        aggregate["difference"][key] = stats([y - x for x, y in zip(b, c)])
        rel = [100.0 * (y - x) / x for x, y in zip(b, c) if abs(x) > 1e-9]
        aggregate["relative_change_pct"][key] = stats(rel) if rel else None
    aggregate["seeds_where_coordinated_used_less_diesel"] = sum(
        r["coordinated"].summary["diesel_litres_tank_adjusted"] < r["baseline"].summary["diesel_litres_tank_adjusted"] for r in runs
    )
    aggregate["seeds"] = args.seeds
    aggregate["days_per_seed"] = args.days
    (out / "aggregate.json").write_text(json.dumps(aggregate, indent=2))

    first = runs[0]
    hourly_keys = list(first["baseline"].hourly)
    with open(out / "hourly_seed0.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["hour", "strategy", "pv_kw", "wind_kw", "essential_kw", "water_demand_m3", *hourly_keys])
        inputs = generate_synthetic_inputs(site, days=args.days, seed=0)
        for name in ("baseline", "coordinated"):
            h = first[name].hourly
            for t in range(inputs.hours):
                writer.writerow([t, name, round(inputs.pv_kw[t], 4), round(inputs.wind_kw[t], 4),
                                 round(inputs.essential_kw[t], 4), round(inputs.water_demand_m3[t], 4),
                                 *(round(float(h[k][t]), 4) for k in hourly_keys)])

    manifest = {
        "description": "Synthetic baseline vs coordinated RO scheduling on an off-grid island model. Not site data.",
        "git_commit": git_commit(),
        "command": "python experiments/run_impact_scenario.py " + " ".join(argv if argv is not None else sys.argv[1:]),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "time_step_hours": 1,
        "days_per_seed": args.days,
        "seeds": list(range(args.seeds)),
        "input_sha256_by_seed": {r["seed"]: r["input_sha256"] for r in runs},
        "assumptions": json.loads(assumptions_record(site, rules)),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    write_markdown(out / "summary.md", aggregate, site, args)
    if args.sensitivity:
        write_sensitivity(out / "sensitivity.csv", args)
    try_plot(out / "impact_seed0.png", first, args.days)
    return aggregate


SENSITIVITY_CASES = [
    ("default", {}, {}),
    ("baseline shift 06-18", {}, {"baseline_shift_start_hour": 6, "baseline_shift_end_hour": 18}),
    ("baseline shift 08-20", {}, {"baseline_shift_start_hour": 8, "baseline_shift_end_hour": 20}),
    ("baseline shift 09-17", {}, {"baseline_shift_start_hour": 9, "baseline_shift_end_hour": 17}),
    ("battery 60 kWh", {"battery_capacity_kwh": 60.0, "battery_min_soc_kwh": 12.0, "battery_initial_soc_kwh": 30.0}, {}),
    ("battery 240 kWh", {"battery_capacity_kwh": 240.0, "battery_min_soc_kwh": 48.0, "battery_initial_soc_kwh": 120.0}, {}),
    ("solar 30 kW", {"pv_rated_kw": 30.0}, {}),
    ("solar 90 kW", {"pv_rated_kw": 90.0}, {}),
    ("water demand 60 m3/day", {"daily_water_demand_m3": 60.0}, {}),
    ("tank 40 m3", {"tank_capacity_m3": 40.0, "tank_initial_m3": 20.0}, {}),
]


def write_sensitivity(path: Path, args) -> None:
    from dataclasses import replace
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case", "mean_adjusted_diesel_change_pct", "min_adjusted_diesel_change_pct", "max_adjusted_diesel_change_pct",
                         "weeks_with_less_diesel", "lowest_water_service_pct_coordinated"])
        for name, site_changes, rule_changes in SENSITIVITY_CASES:
            site = replace(IslandSiteConfig(), **site_changes)
            rules = replace(StrategyRules(), **rule_changes)
            changes, fewer, water = [], 0, []
            for s in range(args.seeds):
                r = compare(generate_synthetic_inputs(site, days=args.days, seed=s), site, rules)
                b, c = r["baseline"].summary, r["coordinated"].summary
                key = "diesel_litres_tank_adjusted"
                changes.append(100.0 * (c[key] - b[key]) / b[key])
                fewer += c[key] < b[key]
                water.append(c["water_service_pct"])
            writer.writerow([name, round(float(np.mean(changes)), 2), round(min(changes), 2), round(max(changes), 2),
                             f"{fewer}/{args.seeds}", round(min(water), 2)])


def write_markdown(path: Path, agg: dict, site: IslandSiteConfig, args) -> None:
    lines = [
        f"# Synthetic impact scenario ({args.seeds} random weeks, simulated)",
        "",
        "Generic off-grid island: "
        f"{site.pv_rated_kw:.0f} kW solar, {site.wind_rated_kw:.0f} kW wind, {site.battery_capacity_kwh:.0f} kWh battery, "
        f"{site.diesel_capacity_kw:.0f} kW diesel, {site.ro_rated_power_kw:.0f} kW RO, {site.tank_capacity_m3:.0f} m3 tank, "
        f"about {site.daily_water_demand_m3:.0f} m3 of water demand per day.",
        "",
        "| Metric (per week, mean over seeds) | Fixed timetable | Coordinated | Change |",
        "|---|---|---|---|",
    ]
    for key, label in HEADLINE:
        b, c = agg["baseline"][key]["mean"], agg["coordinated"][key]["mean"]
        rel = agg["relative_change_pct"][key]
        change = f"{c - b:+.1f}" + (f" ({rel['mean']:+.1f}%)" if rel and key not in ("renewable_used_pct", "water_service_pct", "water_litres_per_household_per_day") else "")
        lines.append(f"| {label} | {b:.1f} | {c:.1f} | {change} |")
    d = agg["relative_change_pct"]["diesel_litres_tank_adjusted"]
    lines += [
        "",
        f"After adjusting for water left in the tank, coordinated scheduling used less diesel in {agg['seeds_where_coordinated_used_less_diesel']} of {args.seeds} weeks. "
        f"The diesel change ranged from {d['min']:+.1f}% to {d['max']:+.1f}% across weeks.",
        "",
        "All numbers are simulation results on synthetic inputs. They show how the model behaves, not what a real island would save.",
    ]
    path.write_text("\n".join(lines) + "\n")


def try_plot(path: Path, run: dict, days: int) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    hours = np.arange(days * 24)
    fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
    for name, colour in (("baseline", "#B5651D"), ("coordinated", "#1F6F8B")):
        h = run[name].hourly
        label = "Fixed timetable" if name == "baseline" else "Coordinated"
        axes[0].plot(hours, h["ro_power_kw"], color=colour, lw=1.2, label=label)
        axes[1].plot(hours, h["diesel_kw"], color=colour, lw=1.2, label=label)
        axes[2].plot(hours, h["tank_m3"], color=colour, lw=1.2, label=label)
    axes[0].set_ylabel("RO power (kW)")
    axes[1].set_ylabel("Diesel (kW)")
    axes[2].set_ylabel("Water in tank (m3)")
    axes[2].set_xlabel("Hour of simulated week (synthetic data, seed 0)")
    axes[0].legend(loc="upper right", frameon=False)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
