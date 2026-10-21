"""Forecast-error robustness experiment for IslandOS dispatch policy selection.

This is a synthetic sensitivity experiment, not a trained forecasting model.
For each case, an optimizer chooses a policy using a perturbed renewable-surplus
forecast; that selected policy is then evaluated against the original synthetic
profile. A fixed-priority baseline is evaluated on the same original profile.
A perfect-information optimizer is reported only as a non-deployable hindsight
reference. Dispatch itself remains reactive to the supplied per-step available
power, so this experiment tests policy-selection sensitivity, not a locked
hour-by-hour schedule under forecast error.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_dispatch_policies import build_scenarios
from optimization.grid_search_optimizer import (
    Candidate, evaluate_candidate, optimize_scenario,
)


def error_profiles(length: int) -> dict[str, tuple[float, ...]]:
    """Deterministic relative forecast-error profiles, bounded to +/-20%."""
    return {
        "perfect": tuple(0.0 for _ in range(length)),
        "overforecast_20pct": tuple(0.20 for _ in range(length)),
        "underforecast_20pct": tuple(-0.20 for _ in range(length)),
        "alternating_pm20pct": tuple(0.20 if i % 2 == 0 else -0.20 for i in range(length)),
    }


def perturb_scenario(scenario, errors):
    forecast = tuple(
        max(0.0, actual * (1.0 + error))
        for actual, error in zip(scenario.available_surplus_kw, errors)
    )
    return replace(scenario, name=scenario.name + "_forecast", available_surplus_kw=forecast)


def _metrics(row: dict) -> dict:
    return {
        "water_unmet_m3": row["water_unmet_m3"],
        "cooling_unmet_kwh_th": row["cooling_unmet_kwh_th"],
        "remaining_surplus_kwh": row["remaining_surplus_kwh"],
        "constraint_violation_hours": row["constraint_violation_hours"],
    }


def run_robustness_experiment() -> list[dict]:
    rows = []
    for actual in build_scenarios():
        for profile_name, errors in error_profiles(len(actual.available_surplus_kw)).items():
            forecast = perturb_scenario(actual, errors)
            forecast_result = optimize_scenario(forecast)
            chosen = forecast_result["recommendation"]
            selected = Candidate(
                candidate_id=chosen["candidate_id"],
                priority=chosen["priority"],
                ro_min_run_hours=chosen["ro_min_run_hours"],
            )
            forecast_selected_actual = evaluate_candidate(actual, selected)

            baseline = evaluate_candidate(
                actual, Candidate("fixed_ro_first_run2h", "ro_first", 2)
            )
            oracle = optimize_scenario(actual)["recommendation"]

            rows.append({
                "scenario": actual.name,
                "forecast_error_profile": profile_name,
                "max_absolute_relative_error": max((abs(x) for x in errors), default=0.0),
                "forecast_selected_candidate": selected.candidate_id,
                "forecast_selected_actual_metrics": _metrics(forecast_selected_actual),
                "fixed_baseline_candidate": "fixed_ro_first_run2h",
                "fixed_baseline_actual_metrics": _metrics(baseline),
                "perfect_information_reference_candidate": oracle["candidate_id"],
                "perfect_information_reference_actual_metrics": _metrics(oracle),
                "data_status": "synthetic sensitivity case; not real forecast or field data",
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()
    rows = run_robustness_experiment()
    if args.json:
        print(json.dumps({
            "data_status": "synthetic sensitivity experiment; not a forecasting model",
            "interpretation": (
                "The forecast chooses a policy candidate; each candidate is then evaluated "
                "against the original synthetic profile. The dispatcher remains reactive, "
                "so results do not represent a locked hourly schedule."
            ),
            "case_count": len(rows),
            "rows": rows,
        }, indent=2))
        return

    print("Synthetic forecast-error policy-selection sensitivity — not field validated")
    print("scenario | error profile | selected | water unmet | cooling unmet | surplus")
    for row in rows:
        m = row["forecast_selected_actual_metrics"]
        print(
            f"{row['scenario']} | {row['forecast_error_profile']} | "
            f"{row['forecast_selected_candidate']} | {m['water_unmet_m3']} | "
            f"{m['cooling_unmet_kwh_th']} | {m['remaining_surplus_kwh']}"
        )


if __name__ == "__main__":
    main()
