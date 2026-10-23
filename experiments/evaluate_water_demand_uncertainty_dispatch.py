"""Compare point water-demand forecasts with an upper-interval planning stress test.

This experiment evaluates two planning assumptions on the same held-out hours:
a point forecast and a conservative upper prediction bound. Actual demand is
kept unchanged for execution and scoring. The upper-bound run is a stress test,
not a claim that the upper bound is a better point forecast.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.build_forecast_dispatch_input import build_forecast_dispatch_input
from experiments.evaluate_forecast_dispatch import (
    load_forecast_water_demand,
    load_paired_series,
)
from experiments.rolling_horizon_dispatch import simulate_rolling


def _forecast_metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Actual and forecast demand must be non-empty and aligned")
    errors = [forecast - observed for observed, forecast in zip(actual, predicted)]
    return {
        "mae_m3_per_hour": sum(abs(error) for error in errors) / len(errors),
        "rmse_m3_per_hour": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_forecast_minus_actual_m3_per_hour": sum(errors) / len(errors),
        "evaluated_hours": len(errors),
    }


def _evaluate_rolling(csv_path: Path) -> tuple[dict[str, Any], dict[str, float]]:
    _, scenario, forecast_surplus = load_paired_series(csv_path)
    actual_water = list(scenario.water_demand_m3_per_hour)
    forecast_water = load_forecast_water_demand(csv_path, actual_water)
    result = simulate_rolling(
        scenario,
        forecast_surplus,
        policy="rolling",
        forecast_water_demand_m3_per_hour=forecast_water,
    )
    water_total = max(sum(actual_water), 1e-9)
    cooling_total = max(sum(scenario.cooling_demand_kw_th), 1e-9)
    surplus_total = max(sum(scenario.available_surplus_kw), 1e-9)
    score = (
        0.45 * result["water_unmet_m3"] / water_total
        + 0.45 * result["cooling_unmet_kwh_th"] / cooling_total
        + 0.10 * result["remaining_surplus_kwh"] / surplus_total
    )
    summary = {
        "normalized_score": round(score, 8),
        "water_unmet_m3": result["water_unmet_m3"],
        "cooling_unmet_kwh_th": result["cooling_unmet_kwh_th"],
        "remaining_surplus_kwh": result["remaining_surplus_kwh"],
        "constraint_violation_hours": result["constraint_violation_hours"],
    }
    return summary, _forecast_metrics(actual_water, forecast_water)


def evaluate_uncertainty_dispatch(
    power_csv: str | Path,
    forecast_report_json: str | Path,
    output_json: str | Path,
    point_column: str = "seasonal_bias_corrected_forecast_m3",
    upper_column: str = "seasonal_bias_corrected_90pct_upper_m3",
) -> dict[str, Any]:
    """Compare point and upper-bound demand planning on the same paired trace."""
    if not point_column.strip() or not upper_column.strip():
        raise ValueError("Point and upper forecast columns must be non-empty")
    if point_column == upper_column:
        raise ValueError("Point and upper forecast columns must be different")

    with tempfile.TemporaryDirectory(prefix="islandos-demand-uncertainty-") as directory:
        root = Path(directory)
        point_csv = root / "point-planning.csv"
        upper_csv = root / "upper-interval-planning.csv"
        point_join = build_forecast_dispatch_input(
            power_csv, forecast_report_json, point_csv, forecast_column=point_column
        )
        upper_join = build_forecast_dispatch_input(
            power_csv, forecast_report_json, upper_csv, forecast_column=upper_column
        )
        if point_join["matched_rows"] != upper_join["matched_rows"]:
            raise ValueError("Point and upper-bound forecasts did not align to the same number of rows")
        if (
            point_join["first_timestamp_utc"] != upper_join["first_timestamp_utc"]
            or point_join["last_timestamp_utc"] != upper_join["last_timestamp_utc"]
        ):
            raise ValueError("Point and upper-bound forecasts do not cover the same time window")

        with point_csv.open("r", encoding="utf-8", newline="") as handle:
            point_rows = list(csv.DictReader(handle))
        with upper_csv.open("r", encoding="utf-8", newline="") as handle:
            upper_rows = list(csv.DictReader(handle))
        for index, (point_row, upper_row) in enumerate(zip(point_rows, upper_rows), start=1):
            if point_row["timestamp_utc"] != upper_row["timestamp_utc"]:
                raise ValueError(f"Point and upper-bound timestamps differ at joined row {index}")
            point_value = float(point_row["forecast_water_demand_m3"])
            upper_value = float(upper_row["forecast_water_demand_m3"])
            if upper_value + 1e-9 < point_value:
                raise ValueError(
                    "Upper-bound forecast must be at least the point forecast "
                    f"at every timestamp (joined row {index})"
                )

        point_dispatch, point_metrics = _evaluate_rolling(point_csv)
        upper_dispatch, upper_metrics = _evaluate_rolling(upper_csv)

    report: dict[str, Any] = {
        "status": "uncertainty_dispatch_comparison_completed",
        "experiment": "point forecast versus upper prediction-bound planning stress test",
        "forecast_report_json": str(forecast_report_json),
        "power_input_csv": str(power_csv),
        "forecast_columns": {
            "point": point_column,
            "upper_bound_stress": upper_column,
        },
        "time_basis": {
            "matched_rows": point_join["matched_rows"],
            "first_timestamp_utc": point_join["first_timestamp_utc"],
            "last_timestamp_utc": point_join["last_timestamp_utc"],
            "interval_hours": 1,
        },
        "point_forecast_planning": {
            "forecast_metrics": point_metrics,
            "rolling_dispatch": point_dispatch,
        },
        "upper_bound_stress_planning": {
            "forecast_metrics": upper_metrics,
            "rolling_dispatch": upper_dispatch,
            "interpretation": (
                "This run plans against the selected upper prediction bound while still "
                "executing and scoring against the same realized demand."
            ),
        },
        "change_upper_minus_point": {
            key: round(upper_dispatch[key] - point_dispatch[key], 8)
            for key in point_dispatch
        },
        "interpretation": (
            "A higher demand planning value can change the RO/cold-storage trade-off. "
            "Compare unmet water, unmet cooling, remaining surplus, constraint violations, "
            "and the illustrative score together. A lower score or lower water deficit on "
            "this trace is not proof of general benefit or operational safety."
        ),
        "limitations": [
            "The upper bound is only meaningful if it comes from a valid out-of-sample interval for the same demand series.",
            "This comparison uses a simplified simulator and a single supplied trace; it is not robust optimization or a live controller.",
            "Actual water demand is preserved for execution and outcome scoring; only the planning input changes.",
            "The illustrative score weights do not replace site-specific service priorities or engineering constraints.",
        ],
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("power_csv", help="Paired hourly power CSV with actual water demand")
    parser.add_argument("forecast_report_json", help="Out-of-sample demand forecast report JSON")
    parser.add_argument("--point-column", default="seasonal_bias_corrected_forecast_m3")
    parser.add_argument("--upper-column", default="seasonal_bias_corrected_90pct_upper_m3")
    parser.add_argument("--output", default="build/forecast-dispatch/uncertainty-comparison.json")
    args = parser.parse_args()
    report = evaluate_uncertainty_dispatch(
        args.power_csv, args.forecast_report_json, args.output,
        point_column=args.point_column, upper_column=args.upper_column,
    )
    print(json.dumps({
        "status": report["status"],
        "time_basis": report["time_basis"],
        "change_upper_minus_point": report["change_upper_minus_point"],
        "output": str(args.output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
