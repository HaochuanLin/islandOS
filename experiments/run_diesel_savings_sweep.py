"""Compare diesel-saving policies across transparent synthetic microgrid stress scenarios.

Run:
    python experiments/run_diesel_savings_sweep.py --seeds 30 --days 7

This reuses IslandOS' existing impact_scenario, energy-system replay and joint
water-energy MILP. It does not create a separate simulator. All inputs are
synthetic; scenarios are controlled experiments, not measured customer sites.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
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
    IslandSiteConfig,
    StrategyRules,
    compare_with_optimizer,
    generate_synthetic_inputs,
)

POLICY_LABELS = {
    "fixed_timetable": "Fixed RO timetable",
    "surplus_rule": "Simple renewable-surplus rule",
    "forecast_rule_realistic": "Forecast rule (20% forecast error, 3 h RO minimum run)",
    "joint_milp": "IslandOS joint water-energy MILP",
}

# Scenario changes are explicit and bounded. They are hypotheses to test,
# not claims about a representative island or a customer installation.
SCENARIOS = {
    "A_reference": {
        "description": "Existing reference configuration; control case.",
        "changes": {},
    },
    "B_diesel_dependent": {
        "description": "Higher essential demand and a smaller renewable fleet; tests a diesel-dependent operating regime.",
        "changes": {
            "pv_rated_kw": 45.0,
            "wind_rated_kw": 30.0,
            "mean_essential_load_kw": 42.0,
            "diesel_capacity_kw": 100.0,
        },
    },
    "C_variable_renewables_limited_storage": {
        "description": "Smaller battery and stronger renewable fleet; tests whether renewable timing and storage coordination reduce diesel runtime.",
        "changes": {
            "pv_rated_kw": 85.0,
            "wind_rated_kw": 65.0,
            "battery_capacity_kwh": 60.0,
            "battery_min_soc_kwh": 12.0,
            "battery_initial_soc_kwh": 30.0,
            "battery_max_charge_kw": 20.0,
            "battery_max_discharge_kw": 20.0,
            "mean_essential_load_kw": 35.0,
        },
    },
    "D_larger_flexible_water_load": {
        "description": "Larger RO plant and water demand with a larger tank; tests the value of shifting a material flexible load.",
        "changes": {
            "pv_rated_kw": 75.0,
            "wind_rated_kw": 50.0,
            "ro_rated_power_kw": 25.0,
            "ro_min_power_kw": 8.0,
            "tank_capacity_m3": 120.0,
            "tank_initial_m3": 60.0,
            "daily_water_demand_m3": 65.0,
            "mean_essential_load_kw": 35.0,
            "diesel_capacity_kw": 100.0,
        },
    },
}

CSV_FIELDS = [
    "scenario", "seed", "input_sha256", "strategy", "strategy_label",
    "diesel_kwh", "diesel_litres", "diesel_litres_tank_adjusted",
    "renewable_available_kwh", "renewable_curtailed_kwh",
    "renewable_used_pct", "water_demand_m3", "water_produced_m3",
    "unmet_water_m3", "water_service_pct", "ending_tank_m3",
    "unmet_electric_kwh", "solver_status", "optimality_proven",
]


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _scenario_site(name: str) -> IslandSiteConfig:
    return replace(IslandSiteConfig(), **SCENARIOS[name]["changes"])


def _row_for_csv(scenario: str, seed: int, input_sha256: str, row: dict, site: IslandSiteConfig, water_demand_m3: float) -> dict:
    strategy = row["strategy"]
    diesel_kwh = float(row.get("diesel_kwh", 0.0))
    curtailed = float(row.get("renewable_curtailed_kwh", 0.0))
    renewable = float(row.get("renewable_available_kwh", 0.0))
    demand = float(water_demand_m3)
    unmet_water = float(row.get("unmet_water_m3", 0.0))
    ending_tank = float(row.get("ending_tank_m3", site.tank_initial_m3))
    water_served = max(0.0, demand - unmet_water)
    water_produced = max(0.0, ending_tank - site.tank_initial_m3 + water_served)
    return {
        "scenario": scenario,
        "seed": seed,
        "input_sha256": input_sha256,
        "strategy": strategy,
        "strategy_label": POLICY_LABELS.get(strategy, strategy),
        "diesel_kwh": diesel_kwh,
        "diesel_litres": float(row.get("diesel_litres", diesel_kwh * site.diesel_litres_per_kwh)),
        "diesel_litres_tank_adjusted": row.get("diesel_litres_tank_adjusted"),
        "renewable_available_kwh": renewable,
        "renewable_curtailed_kwh": curtailed,
        "renewable_used_pct": 100.0 * (renewable - curtailed) / renewable if renewable else 0.0,
        "water_demand_m3": demand,
        "water_produced_m3": water_produced,
        "unmet_water_m3": unmet_water,
        "water_service_pct": 100.0 * water_served / demand if demand else 100.0,
        "ending_tank_m3": ending_tank,
        "unmet_electric_kwh": row.get("unmet_electric_kwh"),
        "solver_status": row.get("solver_status"),
        "optimality_proven": row.get("optimality_proven"),
    }

def _summarise(rows: list[dict]) -> dict:
    by_policy: dict[str, list[dict]] = {}
    for row in rows:
        by_policy.setdefault(row["strategy"], []).append(row)
    if "fixed_timetable" not in by_policy or "surplus_rule" not in by_policy:
        raise ValueError("comparison output is missing a required rule baseline")

    fixed = np.asarray([r["diesel_litres_tank_adjusted"] for r in by_policy["fixed_timetable"]], dtype=float)
    simple = np.asarray([r["diesel_litres_tank_adjusted"] for r in by_policy["surplus_rule"]], dtype=float)
    summary = {}
    for policy, values in by_policy.items():
        litres = np.asarray([r["diesel_litres_tank_adjusted"] for r in values], dtype=float)
        water_shortage = np.asarray([r["unmet_water_m3"] for r in values], dtype=float)
        unserved = np.asarray([r["unmet_electric_kwh"] for r in values], dtype=float)
        item = {
            "n": int(len(litres)),
            "mean_tank_adjusted_diesel_litres": float(litres.mean()),
            "min_tank_adjusted_diesel_litres": float(litres.min()),
            "max_tank_adjusted_diesel_litres": float(litres.max()),
            "mean_unmet_water_m3": float(water_shortage.mean()),
            "mean_unmet_electric_kwh": float(unserved.mean()),
            "all_water_demand_met": bool(np.all(water_shortage <= 1e-6)),
            "all_electric_load_served": bool(np.all(unserved <= 1e-6)),
            "all_milp_optimal": all(r.get("optimality_proven", False) for r in values)
                if policy == "joint_milp" else None,
        }
        item["mean_diesel_saving_vs_fixed_pct"] = float(100 * (fixed.mean() - litres.mean()) / fixed.mean()) if fixed.mean() else 0.0
        item["mean_diesel_saving_vs_simple_rule_pct"] = float(100 * (simple.mean() - litres.mean()) / simple.mean()) if simple.mean() else 0.0
        item["seeds_better_than_fixed"] = int(np.sum(litres < fixed - 1e-8)) if len(litres) == len(fixed) else None
        item["seeds_better_than_simple_rule"] = int(np.sum(litres < simple - 1e-8)) if len(litres) == len(simple) else None
        summary[policy] = item
    return summary


def _write_summary(path: Path, results: dict, seeds: int, days: int) -> None:
    lines = [
        "# Diesel-saving scenario sweep",
        "",
        f"- Synthetic seeds per scenario: {seeds}",
        f"- Horizon per seed: {days} days",
        "- Diesel headline: litres adjusted to restore ending tank inventory to its initial level.",
        "- All policies in a seed use identical weather, essential-load and water-demand inputs.",
        "- No result is a measurement or a validated customer-site performance claim.",
        "",
    ]
    for scenario, payload in results.items():
        lines += [f"## {scenario}", "", payload["description"], "",
                  "| Policy | Mean adjusted diesel (L) | Saving vs fixed | Saving vs simple rule | Better than simple rule | Mean unmet water (m³) |",
                  "|---|---:|---:|---:|---:|---:|"]
        for policy, values in payload["policies"].items():
            better = values["seeds_better_than_simple_rule"]
            better_text = "n/a" if better is None else f"{better}/{seeds}"
            lines.append(
                f"| {POLICY_LABELS.get(policy, policy)} | "
                f"{values['mean_tank_adjusted_diesel_litres']:.2f} | "
                f"{values['mean_diesel_saving_vs_fixed_pct']:+.2f}% | "
                f"{values['mean_diesel_saving_vs_simple_rule_pct']:+.2f}% | "
                f"{better_text} | {values['mean_unmet_water_m3']:.4f} |"
            )
        lines += ["", "Feasibility checks:", ""]
        for policy, values in payload["policies"].items():
            lines.append(
                f"- {POLICY_LABELS.get(policy, policy)}: water met = "
                f"{values['all_water_demand_met']}; electricity served = "
                f"{values['all_electric_load_served']}; MILP optimal = "
                f"{values['all_milp_optimal']}"
            )
        lines.append("")
    lines += [
        "## Interpretation guardrails", "",
        "- A positive saving against the fixed timetable is not sufficient evidence of value.",
        "- The key comparison is against the simple renewable-surplus rule.",
        "- Any policy with unmet water or unserved electricity is not a like-for-like winner.",
        "- The MILP result is optimal only for its declared linear model and assumptions; it is not a real-time forecast result.",
        "- Fuel is calculated with IslandOS' currently configured constant litres-per-kWh factor, not a nonlinear generator fuel curve.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "diesel_savings_sweep")
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be at least 1")
    if not 1 <= args.days <= 7:
        parser.error("--days must be between 1 and 7 (the MILP accepts at most 168 hours)")

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    aggregate = {}
    all_rows = []
    scenario_manifest = {}
    for scenario, spec in SCENARIOS.items():
        site = _scenario_site(scenario)
        rules = StrategyRules()
        scenario_rows = []
        for seed in range(args.seeds):
            inputs = generate_synthetic_inputs(site, days=args.days, seed=seed)
            comparison = compare_with_optimizer(inputs, site, rules, case="island")
            for row in comparison["strategies"]:
                csv_row = _row_for_csv(scenario, seed, comparison["input_sha256"], row, site, float(inputs.water_demand_m3.sum()))
                all_rows.append(csv_row)
                scenario_rows.append(csv_row)
        aggregate[scenario] = {
            "description": spec["description"],
            "assumptions": asdict(site),
            "policies": _summarise(scenario_rows),
        }
        scenario_manifest[scenario] = {
            "description": spec["description"],
            "site": asdict(site),
            "rules": asdict(rules),
        }

    with (output / "per_seed.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)

    (output / "aggregate.json").write_text(json.dumps(aggregate, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "description": "Controlled synthetic diesel-saving sweep using existing IslandOS energy-system replay and joint water-energy MILP.",
        "data_provenance": "Synthetic demo data; not measured site data.",
        "git_commit": _git_commit(),
        "command": "python experiments/run_diesel_savings_sweep.py " + " ".join(argv if argv is not None else sys.argv[1:]),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "seeds": list(range(args.seeds)),
        "days": args.days,
        "scenario_definitions": scenario_manifest,
        "comparison_policies": POLICY_LABELS,
        "fuel_model": "constant litres per kWh from IslandSiteConfig.diesel_litres_per_kwh; nonlinear part-load fuel curve not modelled",
        "forecast_policy": "20% seeded multiplicative renewable forecast error; forecast-based rule is heuristic, not a trained forecast model",
        "model_scope": "synthetic scenario experiment; no site validation; no device-write authority",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _write_summary(output / "summary.md", aggregate, args.seeds, args.days)
    return aggregate


if __name__ == "__main__":
    main()
