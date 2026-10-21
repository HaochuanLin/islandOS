"""Evaluate forecast-driven rolling dispatch on a timestamped, paired power series.

CSV input must contain one row per hour and these columns:
timestamp_utc, actual_surplus_kw, forecast_surplus_kw, water_demand_m3,
cooling_demand_kw_th

The evaluator uses the same realized profile and demands for all policies. The
rolling and fixed-priority policies receive the forecast series; the
perfect_information policy uses realized surplus only as a non-deployable
hindsight reference. This evaluates the dispatch interface, not a forecast
model, and cannot establish real-island performance without suitable site data.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_dispatch_policies import Scenario
from experiments.rolling_horizon_dispatch import simulate_rolling

REQUIRED_COLUMNS = (
    "timestamp_utc",
    "actual_surplus_kw",
    "forecast_surplus_kw",
    "water_demand_m3",
    "cooling_demand_kw_th",
)


def _parse_timestamp(value: str, line: int) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp_utc at CSV line {line}: {value!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"timestamp_utc must include a timezone at CSV line {line}")
    return stamp


def _parse_nonnegative(row: dict[str, str], column: str, line: int) -> float:
    raw = (row.get(column) or "").strip()
    if not raw:
        raise ValueError(f"Missing {column} at CSV line {line}")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Non-numeric {column} at CSV line {line}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{column} must be finite and non-negative at CSV line {line}")
    return value


def load_paired_series(input_csv: str | Path) -> tuple[list[str], Scenario, list[float]]:
    """Load and validate paired forecast/realization rows without imputing data."""
    input_path = Path(input_csv)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    if not rows:
        raise ValueError("Input CSV must contain at least one hourly row")

    timestamps: list[str] = []
    parsed_timestamps: list[datetime] = []
    actual: list[float] = []
    forecast: list[float] = []
    water: list[float] = []
    cooling: list[float] = []

    for line, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp_utc", ""), line)
        if parsed_timestamps:
            elapsed = (stamp.astimezone().timestamp()
                       - parsed_timestamps[-1].astimezone().timestamp())
            if elapsed != 3600:
                raise ValueError(
                    f"Expected strictly ordered hourly timestamps at CSV line {line}"
                )
        parsed_timestamps.append(stamp)
        timestamps.append(stamp.isoformat().replace("+00:00", "Z"))
        actual.append(_parse_nonnegative(row, "actual_surplus_kw", line))
        forecast.append(_parse_nonnegative(row, "forecast_surplus_kw", line))
        water.append(_parse_nonnegative(row, "water_demand_m3", line))
        cooling.append(_parse_nonnegative(row, "cooling_demand_kw_th", line))

    scenario = Scenario(
        name=input_path.stem,
        available_surplus_kw=tuple(actual),
        water_demand_m3_per_hour=tuple(water),
        cooling_demand_kw_th=tuple(cooling),
    )
    return timestamps, scenario, forecast


def _forecast_metrics(actual: list[float], forecast: list[float]) -> dict:
    errors = [predicted - observed for observed, predicted in zip(actual, forecast)]
    return {
        "mae_kw": sum(abs(error) for error in errors) / len(errors),
        "rmse_kw": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_forecast_minus_actual_kw": sum(errors) / len(errors),
        "evaluated_hours": len(errors),
    }


def _score(result: dict, scenario: Scenario) -> float:
    water_total = max(sum(scenario.water_demand_m3_per_hour), 1e-9)
    cooling_total = max(sum(scenario.cooling_demand_kw_th), 1e-9)
    surplus_total = max(sum(scenario.available_surplus_kw), 1e-9)
    return (
        0.45 * result["water_unmet_m3"] / water_total
        + 0.45 * result["cooling_unmet_kwh_th"] / cooling_total
        + 0.10 * result["remaining_surplus_kwh"] / surplus_total
    )


def evaluate_forecast_dispatch(input_csv: str | Path) -> dict:
    timestamps, scenario, forecast = load_paired_series(input_csv)
    actual = list(scenario.available_surplus_kw)
    policies = {}
    for policy in ("rolling", "ro_first", "ice_first", "perfect_information"):
        result = simulate_rolling(scenario, forecast, policy)
        policies[policy] = {
            **result,
            "normalized_score": round(_score(result, scenario), 8),
        }

    fixed = {name: policies[name]["normalized_score"] for name in ("ro_first", "ice_first")}
    best_fixed = min(fixed, key=lambda name: (fixed[name], name))
    rolling_score = policies["rolling"]["normalized_score"]
    return {
        "experiment": "paired forecast-to-dispatch evaluation",
        "input_csv": str(input_csv),
        "data_status": "user-supplied paired series; provenance and realism are not independently verified",
        "time_basis": {
            "rows": len(timestamps),
            "first_timestamp_utc": timestamps[0],
            "last_timestamp_utc": timestamps[-1],
            "interval_hours": 1,
        },
        "forecast_metrics": _forecast_metrics(actual, forecast),
        "score_definition": (
            "0.45 * unmet water / total water demand + "
            "0.45 * unmet cooling / total cooling demand + "
            "0.10 * remaining surplus / total actual surplus; lower is better"
        ),
        "policy_comparison": policies,
        "comparison": {
            "best_fixed_policy": best_fixed,
            "best_fixed_score": fixed[best_fixed],
            "rolling_score": rolling_score,
            "rolling_minus_best_fixed": round(rolling_score - fixed[best_fixed], 8),
            "interpretation": (
                "Negative rolling_minus_best_fixed means rolling has a lower score "
                "for this input series only. Do not generalize from one trace."
            ),
        },
        "limitations": [
            "This evaluates dispatch given a supplied forecast; it does not train or validate a forecast model.",
            "Forecast and realized surplus must be paired by timestamp and use the same kW unit.",
            "Water and cooling demand inputs are treated as known over the tested horizon.",
            "The score weights are illustrative; inspect raw service-deficit metrics as well.",
            "The perfect_information policy is a hindsight reference, not deployable control.",
            "The simulator is simplified and does not model plant interlocks, ramping, or site-specific safety limits.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly CSV with paired actual and forecast surplus")
    parser.add_argument("--output", default="build/forecast-dispatch-evaluation.json")
    args = parser.parse_args()
    try:
        result = evaluate_forecast_dispatch(args.input_csv)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "output": str(output),
        "forecast_metrics": result["forecast_metrics"],
        "comparison": result["comparison"],
        "policy_scores": {
            name: value["normalized_score"]
            for name, value in result["policy_comparison"].items()
        },
        "data_status": result["data_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
