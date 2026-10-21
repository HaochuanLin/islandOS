"""Audit rolling-dispatch outcomes under alternative objective weights.

This script re-scores identical synthetic simulation outcomes; it does not rerun
dispatch or claim that any illustrative weight set represents stakeholder values.
"""
from __future__ import annotations

import argparse
import json
from experiments.rolling_horizon_dispatch import run_experiment
from experiments.compare_dispatch_policies import build_scenarios

WEIGHT_SETS = {
    "balanced_reliability": (0.45, 0.45, 0.10),
    "water_priority": (0.70, 0.20, 0.10),
    "cooling_priority": (0.20, 0.70, 0.10),
    "surplus_priority": (0.40, 0.40, 0.20),
    "equal_objectives": (1 / 3, 1 / 3, 1 / 3),
}


def summarize_weight_sensitivity(rows=None):
    if rows is None:
        rows = run_experiment()
    scenarios = {s.name: s for s in build_scenarios()}
    grouped = {}
    for row in rows:
        key = (row["scenario"], row["forecast_error_profile"])
        grouped.setdefault(key, {})[row["result"]["policy"]] = row["result"]

    output = []
    for weight_name, weights in WEIGHT_SETS.items():
        deltas = []
        for (scenario_name, error_name), policies in sorted(grouped.items()):
            scenario = scenarios[scenario_name]
            water_total = max(sum(scenario.water_demand_m3_per_hour), 1e-9)
            cooling_total = max(sum(scenario.cooling_demand_kw_th), 1e-9)
            power_total = max(sum(scenario.available_surplus_kw), 1e-9)

            def score(result):
                return (
                    weights[0] * result["water_unmet_m3"] / water_total
                    + weights[1] * result["cooling_unmet_kwh_th"] / cooling_total
                    + weights[2] * result["remaining_surplus_kwh"] / power_total
                )

            rolling = score(policies["rolling"])
            fixed = min(score(policies["ro_first"]), score(policies["ice_first"]))
            deltas.append(rolling - fixed)
        output.append({
            "weight_set": weight_name,
            "weights": {
                "water_unmet": weights[0],
                "cooling_unmet": weights[1],
                "remaining_surplus": weights[2],
            },
            "case_count": len(deltas),
            "rolling_wins": sum(x < -1e-9 for x in deltas),
            "ties": sum(abs(x) <= 1e-9 for x in deltas),
            "rolling_losses": sum(x > 1e-9 for x in deltas),
            "mean_delta": round(sum(deltas) / max(len(deltas), 1), 6),
            "min_delta": round(min(deltas), 6),
            "max_delta": round(max(deltas), 6),
            "interpretation": "synthetic cases; weights are illustrative, not stakeholder-validated",
        })
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = summarize_weight_sensitivity()
    if args.json:
        print(json.dumps({"weight_sets_tested": len(summary), "summary": summary}, indent=2))
    else:
        print("Weight sensitivity audit — synthetic outcomes only")
        print("weights | wins | ties | losses | mean delta")
        for row in summary:
            print(f"{row['weight_set']} | {row['rolling_wins']} | {row['ties']} | "
                  f"{row['rolling_losses']} | {row['mean_delta']:+.4f}")


if __name__ == "__main__":
    main()
