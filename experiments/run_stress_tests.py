"""Forecast stress scenarios and water-shortage stress tests on synthetic weeks.

Part 1 (forecast stress): build the four directional stress scenarios from
synthetic forecast intervals (renewables -30%, demand +15%, prices +25%),
re-plan the joint MILP on each, and report how much the schedule moves.
Then hold the central plan and the combined-stress plan and replay each in
every scenario, to see the cost and water shortage when the forecast is wrong.

Part 2 (water shortage): run every strategy through three named events
(low-renewable week, two-day water demand spike, both) and count water
shortage.

All inputs are synthetic. Results compare strategies; they are not site data.

    python experiments/run_stress_tests.py --seeds 10
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from islandos_core.impact_scenario import IslandSiteConfig, StrategyRules, assumptions_record, generate_synthetic_inputs  # noqa: E402
from islandos_core.stress_dispatch import STRESS_EVENTS, forecast_stress_study, water_shortage_stress_test  # noqa: E402

CASES = ("island", "grid_tou")
SCENARIOS = ("central", "renewable_low_demand_high", "cost_high", "combined_stress")
STRATEGY_LABELS = {
    "fixed_timetable": "Fixed RO timetable",
    "surplus_rule": "Surplus rule",
    "forecast_rule": "Forecast-based rule",
    "joint_milp_planned_on_normal_forecast": "Joint MILP, planned on normal forecast",
    "joint_milp_with_reserve_planned_on_normal_forecast": "Joint MILP with 20 m3 reserve, normal forecast",
    "joint_milp_event_forecast": "Joint MILP, event forecast in advance",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "stress_tests")
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be at least 1")
    site, rules = IslandSiteConfig(), StrategyRules()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    forecast_rows, shortage_rows = [], []
    for case in CASES:
        for seed in range(args.seeds):
            inputs = generate_synthetic_inputs(site, days=7, seed=seed)
            study = forecast_stress_study(inputs, site, case)
            for name, change in study["schedule_change"].items():
                forecast_rows.append({"case": case, "seed": seed, "kind": "schedule_change", "scenario": name, **change})
            for plan, outcomes in study["plan_outcomes"].items():
                for realised, values in outcomes.items():
                    forecast_rows.append({"case": case, "seed": seed, "kind": "outcome", "plan": plan,
                                          "scenario": realised, **values})
            for event in STRESS_EVENTS:
                shortage_rows.extend({"seed": seed, **row} for row in water_shortage_stress_test(inputs, site, event, case, rules))
            print(f"{case} seed {seed} done", flush=True)

    with (out / "forecast_stress_rows.json").open("w", encoding="utf-8") as handle:
        json.dump(forecast_rows, handle, indent=1)
    fields = ["case", "event", "seed", "strategy", "water_shortage_m3", "min_tank_m3", "headline_tank_adjusted",
              "energy_cost", "diesel_kwh", "unmet_electric_kwh", "ending_tank_m3", "infeasible"]
    with (out / "water_shortage_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(shortage_rows)
    (out / "manifest.json").write_text(json.dumps({
        "description": "Forecast stress and water-shortage stress tests on synthetic weeks. Not site data.",
        "command": "python experiments/run_stress_tests.py " + " ".join(argv if argv is not None else sys.argv[1:]),
        "python": platform.python_version(), "numpy": np.__version__,
        "seeds": list(range(args.seeds)),
        "forecast_interval_bands": {"renewable": 0.3, "demand": 0.15, "price": 0.25},
        "stress_events": {"low_renewable_factor": 0.4, "demand_spike_factor": 1.6, "spike_days": [2, 4]},
        "milp_reserve_m3": 20.0,
        "assumptions": json.loads(assumptions_record(site, rules)),
    }, indent=2), encoding="utf-8")
    write_summary(out / "summary.md", forecast_rows, shortage_rows, args.seeds)
    print((out / "summary.md").read_text(encoding="utf-8"))
    return 0


def _mean(values):
    values = list(values)
    return statistics.mean(values) if values else float("nan")


def write_summary(path: Path, forecast_rows: list[dict], shortage_rows: list[dict], seeds: int) -> None:
    lines = [f"# Stress tests ({seeds} synthetic weeks per case)", "",
             "## 1. Does the optimizer change its schedule under forecast stress?", "",
             "Mean over weeks. RO energy moved is half the total absolute change in hourly RO power versus the central plan.", "",
             "| Case | Scenario | Weeks where schedule changed | RO energy moved (kWh) | RO hours changed | Planned cost change |",
             "|---|---|---|---|---|---|"]
    for case in CASES:
        for scenario in SCENARIOS[1:]:
            rows = [r for r in forecast_rows if r["case"] == case and r["kind"] == "schedule_change" and r["scenario"] == scenario]
            lines.append(f"| {case} | {scenario} | {sum(r['schedule_changed'] for r in rows)}/{len(rows)} | "
                         f"{_mean(r['ro_energy_moved_kwh'] for r in rows):.0f} | {_mean(r['ro_hours_changed'] for r in rows):.0f} | "
                         f"{_mean(r['planned_cost_change_vs_central_pct'] for r in rows):+.0f}% |")
    lines += ["", "## 2. What happens when the plan was made on the wrong forecast?", "",
              "Each plan's RO schedule is held; the battery-first controller runs the electricity live. "
              "Headline is tank-adjusted diesel litres (island) or tank-adjusted cost in USD (grid_tou). "
              "Water shortage is the total over all weeks. A lower headline next to a shortage is not a saving: "
              "that plan simply delivered less water.", "",
              "| Case | Plan made on | Realised scenario | Mean headline | Water shortage (m3) |",
              "|---|---|---|---|---|"]
    for case in CASES:
        for plan in ("central", "combined_stress"):
            for scenario in SCENARIOS:
                rows = [r for r in forecast_rows if r["case"] == case and r["kind"] == "outcome"
                        and r["plan"] == plan and r["scenario"] == scenario]
                lines.append(f"| {case} | {plan} | {scenario} | {_mean(r['headline_tank_adjusted'] for r in rows):.1f} | "
                             f"{sum(r['water_shortage_m3'] for r in rows):.1f} |")
    lines += ["", "## 3. Water-shortage stress events", "",
              "Water shortage and lowest tank level are totals and minimums over all weeks. "
              "Headline as above, mean per week; again, a lower headline with a shortage means less water was delivered.", "",
              "| Case | Event | Strategy | Weeks with shortage | Water shortage (m3) | Lowest tank (m3) | Mean headline |",
              "|---|---|---|---|---|---|---|"]
    for case in CASES:
        for event in STRESS_EVENTS:
            for strategy, label in STRATEGY_LABELS.items():
                rows = [r for r in shortage_rows if r["case"] == case and r["event"] == event and r["strategy"] == strategy]
                ok = [r for r in rows if "infeasible" not in r]
                if not rows:
                    continue
                infeasible = len(rows) - len(ok)
                lines.append(
                    f"| {case} | {event} | {label} | {sum(r['water_shortage_m3'] > 1e-6 for r in ok)}/{len(rows)}"
                    f"{f' ({infeasible} infeasible)' if infeasible else ''} | {sum(r['water_shortage_m3'] for r in ok):.1f} | "
                    f"{min((r['min_tank_m3'] for r in ok), default=float('nan')):.1f} | "
                    f"{_mean(r['headline_tank_adjusted'] for r in ok):.1f} |")
    lines += ["", "All numbers are simulation results on synthetic inputs, not measurements."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
