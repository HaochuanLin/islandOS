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
from datetime import datetime, timezone
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
    # The schema promises UTC; accept explicit offsets but normalize them before
    # reporting timestamps so local-offset strings are never mislabeled as UTC.
    return stamp.astimezone(timezone.utc)


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


def has_forecast_water_demand_column(input_csv: str | Path) -> bool:
    with Path(input_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        return "forecast_water_demand_m3" in (csv.DictReader(handle).fieldnames or [])


def load_forecast_water_demand(input_csv: str | Path, actual_demand: list[float]) -> list[float]:
    """Load optional water-demand forecasts; fall back to realized demand for legacy inputs."""
    input_path = Path(input_csv)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "forecast_water_demand_m3" not in (reader.fieldnames or []):
            return list(actual_demand)
        rows = list(reader)
    if len(rows) != len(actual_demand):
        raise ValueError("forecast_water_demand_m3 row count must match actual water demand")
    forecast = []
    for line, row in enumerate(rows, start=2):
        value = _parse_nonnegative(row, "forecast_water_demand_m3", line)
        forecast.append(value)
    return forecast


def _forecast_metrics(actual: list[float], forecast: list[float]) -> dict:
    errors = [predicted - observed for observed, predicted in zip(actual, forecast)]
    return {
        "mae_kw": sum(abs(error) for error in errors) / len(errors),
        "rmse_kw": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_forecast_minus_actual_kw": sum(errors) / len(errors),
        "evaluated_hours": len(errors),
    }


def _water_forecast_metrics(actual: list[float], forecast: list[float]) -> dict:
    errors = [predicted - observed for observed, predicted in zip(actual, forecast)]
    return {
        "mae_m3_per_hour": sum(abs(error) for error in errors) / len(errors),
        "rmse_m3_per_hour": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_forecast_minus_actual_m3_per_hour": sum(errors) / len(errors),
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


def _evaluate_policies(scenario: Scenario, forecast: list[float], forecast_water: list[float] | None = None) -> dict:
    """Evaluate all dispatch policies on one shared realized profile."""
    policies = {}
    for policy in ("rolling", "ro_first", "ice_first", "perfect_information"):
        result = simulate_rolling(
            scenario, forecast, policy,
            forecast_water_demand_m3_per_hour=forecast_water,
        )
        policies[policy] = {
            **result,
            "normalized_score": round(_score(result, scenario), 8),
        }
    fixed = {name: policies[name]["normalized_score"] for name in ("ro_first", "ice_first")}
    best_fixed = min(fixed, key=lambda name: (fixed[name], name))
    rolling_score = policies["rolling"]["normalized_score"]
    return {
        "policies": policies,
        "comparison": {
            "best_fixed_policy": best_fixed,
            "best_fixed_score": fixed[best_fixed],
            "rolling_score": rolling_score,
            "rolling_minus_best_fixed": round(rolling_score - fixed[best_fixed], 8),
        },
    }


def evaluate_forecast_dispatch(input_csv: str | Path) -> dict:
    timestamps, scenario, forecast = load_paired_series(input_csv)
    actual = list(scenario.available_surplus_kw)
    forecast_water = load_forecast_water_demand(input_csv, list(scenario.water_demand_m3_per_hour))
    full_evaluation = _evaluate_policies(scenario, forecast, forecast_water)

    # A one-step persistence forecast at time t uses only realized surplus at t-1.
    # Compare both forecasts on rows 2..N so neither gets a special first-hour case.
    if len(actual) >= 2:
        aligned_actual = actual[1:]
        supplied_aligned = forecast[1:]
        persistence_forecast = actual[:-1]
        aligned_scenario = Scenario(
            name=f"{scenario.name}_aligned_comparison",
            available_surplus_kw=tuple(aligned_actual),
            water_demand_m3_per_hour=scenario.water_demand_m3_per_hour[1:],
            cooling_demand_kw_th=scenario.cooling_demand_kw_th[1:],
        )
        supplied_metrics = _forecast_metrics(aligned_actual, supplied_aligned)
        persistence_metrics = _forecast_metrics(aligned_actual, persistence_forecast)
        persistence_mae = persistence_metrics["mae_kw"]
        persistence_rmse = persistence_metrics["rmse_kw"]
        aligned_forecast_water = forecast_water[1:]
        supplied_dispatch = _evaluate_policies(aligned_scenario, supplied_aligned, aligned_forecast_water)
        persistence_dispatch = _evaluate_policies(aligned_scenario, persistence_forecast, aligned_forecast_water)
        baseline_comparison = {
            "status": "evaluated",
            "method": "one-step persistence: forecast[t] = actual_surplus[t-1]",
            "aligned_hours": len(aligned_actual),
            "first_aligned_timestamp_utc": timestamps[1],
            "last_aligned_timestamp_utc": timestamps[-1],
            "forecast_metrics": {
                "supplied_forecast": supplied_metrics,
                "persistence_baseline": persistence_metrics,
                "mae_skill_vs_persistence": (
                    round((persistence_mae - supplied_metrics["mae_kw"]) / persistence_mae, 8)
                    if persistence_mae > 0 else None
                ),
                "rmse_skill_vs_persistence": (
                    round((persistence_rmse - supplied_metrics["rmse_kw"]) / persistence_rmse, 8)
                    if persistence_rmse > 0 else None
                ),
                "skill_interpretation": (
                    "Positive skill means the supplied forecast has lower error than persistence; "
                    "null means the persistence denominator is zero."
                ),
            },
            "dispatch_comparison": {
                "supplied_forecast": supplied_dispatch,
                "persistence_baseline": persistence_dispatch,
                "rolling_score_difference_supplied_minus_persistence": round(
                    supplied_dispatch["comparison"]["rolling_score"]
                    - persistence_dispatch["comparison"]["rolling_score"], 8
                ),
                "interpretation": (
                    "Both dispatch runs use the same aligned realized surplus, demand series, "
                    "initial inventory assumptions and simulator. Negative difference means "
                    "supplied-forecast rolling dispatch scored lower on this aligned window only."
                ),
            },
        }
    else:
        baseline_comparison = {
            "status": "not_evaluated",
            "reason": "At least two hourly rows are required to construct a one-step persistence forecast.",
        }

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
        "water_demand_input": {
            "forecast_column_used": "forecast_water_demand_m3" if has_forecast_water_demand_column(input_csv) else "actual_demand_fallback",
            "actual_demand_is_used_for_execution": True,
            "forecast_demand_is_used_for_planning": True,
            "forecast_demand_metrics": _water_forecast_metrics(
                list(scenario.water_demand_m3_per_hour), forecast_water
            ),
        },
        "score_definition": (
            "0.45 * unmet water / total water demand + "
            "0.45 * unmet cooling / total cooling demand + "
            "0.10 * remaining surplus / total actual surplus; lower is better"
        ),
        "policy_comparison": full_evaluation["policies"],
        "comparison": {
            **full_evaluation["comparison"],
            "interpretation": (
                "Negative rolling_minus_best_fixed means rolling has a lower score "
                "for this input series only. Do not generalize from one trace."
            ),
        },
        "persistence_baseline_comparison": baseline_comparison,
        "limitations": [
            "This evaluates dispatch given a supplied forecast; it does not train or validate a forecast model.",
            "The persistence comparison excludes the first row for both forecasts and dispatch policies so the evaluation window is aligned.",
            "Persistence uses only the previous observed surplus; this is a simple benchmark, not a universally appropriate forecast.",
            "The aligned dispatch comparison resets initial inventories equally for both forecast inputs; it is a controlled window comparison, not continuation of the full-horizon run.",
            "Forecast and realized surplus must be paired by timestamp and use the same kW unit.",
            "If forecast_water_demand_m3 is absent, realized water demand is used for planning as a legacy compatibility fallback; this is a hindsight assumption, not a deployable forecast.",
            "When forecast_water_demand_m3 is present, it is used for planning while actual water_demand_m3 is used for execution and outcome accounting.",
            "Cooling demand is treated as known over the tested horizon.",
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
