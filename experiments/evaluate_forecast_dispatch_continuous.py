"""Continuous-state forecast-to-dispatch backtest over one chronological trace.

Unlike the independent-window evaluator, this runs each strategy across the
entire input series so water and thermal inventories carry from hour to hour.
The persistence strategy shares the supplied forecast for hour 0 as a common
warm-up action; from hour 1 onward, its forecast is actual surplus from the
previous hour. Forecast-error metrics exclude that shared warm-up hour.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.evaluate_forecast_dispatch import (
    _forecast_metrics,
    load_paired_series,
)
from experiments.rolling_horizon_dispatch import simulate_rolling


def _score(result: dict, scenario) -> float:
    """Use the same illustrative normalized service/surplus score as the evaluator."""
    water_total = max(sum(scenario.water_demand_m3_per_hour), 1e-9)
    cooling_total = max(sum(scenario.cooling_demand_kw_th), 1e-9)
    surplus_total = max(sum(scenario.available_surplus_kw), 1e-9)
    return (
        0.45 * result["water_unmet_m3"] / water_total
        + 0.45 * result["cooling_unmet_kwh_th"] / cooling_total
        + 0.10 * result["remaining_surplus_kwh"] / surplus_total
    )


def build_persistence_forecast(actual: list[float], shared_first_forecast: float) -> list[float]:
    """Use a common first-hour warm-up, then only the previous observed actual."""
    if len(actual) < 2:
        raise ValueError("At least two hourly rows are required for persistence evaluation")
    return [shared_first_forecast, *actual[:-1]]


def evaluate_continuous(input_csv: str | Path) -> dict:
    timestamps, scenario, supplied_forecast = load_paired_series(input_csv)
    actual = list(scenario.available_surplus_kw)
    if len(actual) < 2:
        raise ValueError("At least two hourly rows are required for continuous baseline evaluation")

    persistence_forecast = build_persistence_forecast(actual, supplied_forecast[0])
    aligned_actual = actual[1:]
    supplied_metrics = _forecast_metrics(aligned_actual, supplied_forecast[1:])
    persistence_metrics = _forecast_metrics(aligned_actual, persistence_forecast[1:])

    # Every strategy runs from hour 0 through the end, with its own state carried
    # continuously. Initial conditions are identical because each simulation
    # constructs the same default RO and thermal-storage configurations.
    supplied = simulate_rolling(scenario, supplied_forecast, "rolling")
    persistence = simulate_rolling(scenario, persistence_forecast, "rolling")
    fixed_ro = simulate_rolling(scenario, supplied_forecast, "ro_first")
    fixed_ice = simulate_rolling(scenario, supplied_forecast, "ice_first")
    hindsight = simulate_rolling(scenario, actual, "perfect_information")

    scored = {
        "supplied_forecast_rolling": supplied,
        "persistence_rolling": persistence,
        "ro_first_using_supplied_forecast": fixed_ro,
        "ice_first_using_supplied_forecast": fixed_ice,
        "perfect_information_hindsight_only": hindsight,
    }
    scores = {name: round(_score(result, scenario), 8) for name, result in scored.items()}
    best_fixed = min(
        ("ro_first_using_supplied_forecast", "ice_first_using_supplied_forecast"),
        key=lambda name: (scores[name], name),
    )
    return {
        "experiment": "continuous-state chronological forecast-to-dispatch backtest",
        "input_csv": str(input_csv),
        "data_status": "user-supplied paired series; provenance and realism are not independently verified",
        "time_basis": {
            "rows": len(timestamps),
            "first_timestamp_utc": timestamps[0],
            "last_timestamp_utc": timestamps[-1],
            "interval_hours": 1,
        },
        "state_handling": {
            "inventory_carryover": "water and thermal inventories carry hour-to-hour within each full-trace simulation",
            "initial_conditions": "all strategies start from the simulator's same default inventories",
            "persistence_warmup": "hour 0 uses the supplied forecast for both rolling strategies; from hour 1 onward persistence uses actual surplus from hour t-1",
            "forecast_metrics_hours": len(aligned_actual),
            "dispatch_score_hours": len(actual),
        },
        "forecast_metrics_on_aligned_hours": {
            "supplied_forecast": supplied_metrics,
            "persistence_baseline": persistence_metrics,
            "mae_skill_vs_persistence": (
                (persistence_metrics["mae_kw"] - supplied_metrics["mae_kw"])
                / persistence_metrics["mae_kw"]
                if persistence_metrics["mae_kw"] > 0 else None
            ),
            "rmse_skill_vs_persistence": (
                (persistence_metrics["rmse_kw"] - supplied_metrics["rmse_kw"])
                / persistence_metrics["rmse_kw"]
                if persistence_metrics["rmse_kw"] > 0 else None
            ),
        },
        "score_definition": (
            "0.45 * unmet water / total water demand + "
            "0.45 * unmet cooling / total cooling demand + "
            "0.10 * remaining surplus / total actual surplus; lower is better"
        ),
        "policy_scores": scores,
        "comparisons": {
            "supplied_minus_persistence_rolling_score": round(
                scores["supplied_forecast_rolling"] - scores["persistence_rolling"], 8
            ),
            "best_fixed_policy": best_fixed,
            "supplied_rolling_minus_best_fixed_score": round(
                scores["supplied_forecast_rolling"] - scores[best_fixed], 8
            ),
            "interpretation": (
                "Negative score differences favor the first named policy on this trace only; "
                "do not generalize without multiple suitable traces and sensitivity analysis."
            ),
        },
        "results": scored,
        "limitations": [
            "The input data provenance and realism are not independently verified.",
            "Persistence shares the supplied first-hour forecast as a common warm-up; forecast metrics exclude that hour, while full-trace dispatch scores include it.",
            "Each strategy is a separate run with identical initial inventory assumptions; inventory is continuous within each run, not shared between competing strategies.",
            "Water and cooling demands are treated as known over the planning horizon.",
            "The perfect-information result is a hindsight-only reference and is not deployable.",
            "The simulator is simplified and does not model plant interlocks, ramping, thermal leakage, or site-specific safety limits.",
            "The normalized score uses illustrative weights; inspect raw deficits, remaining surplus, final inventories, and constraint violations.",
            "This is a dispatch backtest, not proof of field performance or a validated renewable-power forecast.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly CSV with paired actual and forecast surplus")
    parser.add_argument("--output", default="build/forecast-dispatch-continuous.json")
    args = parser.parse_args()
    try:
        result = evaluate_continuous(args.input_csv)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "output": str(output),
        "rows": result["time_basis"]["rows"],
        "forecast_metrics": result["forecast_metrics_on_aligned_hours"],
        "policy_scores": result["policy_scores"],
        "comparisons": result["comparisons"],
        "data_status": result["data_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
