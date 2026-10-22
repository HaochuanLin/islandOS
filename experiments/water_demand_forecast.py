"""Evaluate simple probabilistic freshwater-demand forecast baselines.

Input is hourly historical demand with columns `timestamp` and
`water_demand_m3`. The script compares persistence and 24-hour seasonal-naive
forecasts, then checks (rather than assumes) whether demand and forecast errors
look Gaussian. It is a baseline, not a trained or continuously learning model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

SEASONAL_LAG_HOURS = 24
Z_90 = 1.6448536269514722
Z_95 = 1.959963984540054


def _parse_timestamp(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp: {value!r}") from exc
    if stamp.tzinfo is None:
        raise ValueError("timestamp must include a timezone offset")
    return stamp


def _metrics(actual: list[float], predicted: list[float]) -> dict:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metric inputs must be non-empty and aligned")
    errors = [p - a for a, p in zip(actual, predicted)]
    return {
        "mae_m3_per_hour": sum(abs(error) for error in errors) / len(errors),
        "rmse_m3_per_hour": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_predicted_minus_actual_m3_per_hour": sum(errors) / len(errors),
    }


def _normality_diagnostic(values: list[float]) -> dict:
    """Descriptive Jarque-Bera diagnostic; p-value is asymptotic, not a verdict."""
    n = len(values)
    if n < 8:
        return {
            "sample_count": n,
            "available": False,
            "reason": "At least 8 values are needed for this descriptive diagnostic.",
        }
    mean = sum(values) / n
    centered = [value - mean for value in values]
    m2 = sum(value * value for value in centered) / n
    if m2 <= 1e-15:
        return {
            "sample_count": n,
            "available": False,
            "reason": "Values have zero or near-zero variance.",
        }
    m3 = sum(value ** 3 for value in centered) / n
    m4 = sum(value ** 4 for value in centered) / n
    skewness = m3 / (m2 ** 1.5)
    excess_kurtosis = m4 / (m2 ** 2) - 3.0
    jb = n / 6.0 * (skewness ** 2 + (excess_kurtosis ** 2) / 4.0)
    # Under the asymptotic chi-square distribution with 2 degrees of freedom.
    p_value = math.exp(-jb / 2.0)
    return {
        "sample_count": n,
        "available": True,
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "jarque_bera_statistic": jb,
        "approximate_p_value": p_value,
        "interpretation": (
            "A small p-value is evidence against a Gaussian shape; a large p-value "
            "does not prove normality. Inspect the time pattern and sample size too."
        ),
    }


def evaluate_water_demand(
    input_csv: str | Path,
    output_json: str | Path,
    test_fraction: float = 0.25,
) -> dict:
    """Chronologically evaluate one-step hourly demand forecasts."""
    if not 0.10 <= test_fraction <= 0.50:
        raise ValueError("test_fraction must be between 0.10 and 0.50")

    input_path = Path(input_csv)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "water_demand_m3"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    if len(rows) < SEASONAL_LAG_HOURS + 12:
        raise ValueError(
            f"Need at least {SEASONAL_LAG_HOURS + 12} hourly rows for a chronological holdout"
        )

    timestamps: list[datetime] = []
    demand: list[float] = []
    for line, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp") or "")
        if timestamps:
            delta = (stamp - timestamps[-1]).total_seconds()
            if delta != 3600:
                raise ValueError(
                    f"Expected strictly ordered, continuous hourly records at CSV line {line}"
                )
        raw = (row.get("water_demand_m3") or "").strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid water_demand_m3 at CSV line {line}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(
                f"water_demand_m3 must be finite and non-negative at CSV line {line}"
            )
        timestamps.append(stamp)
        demand.append(value)

    split = int(len(demand) * (1.0 - test_fraction))
    if split < SEASONAL_LAG_HOURS + 8 or split >= len(demand):
        raise ValueError("Not enough history or holdout rows for the requested split")

    # Forecast target t using only observations before t.
    train_indices = list(range(SEASONAL_LAG_HOURS, split))
    test_indices = list(range(split, len(demand)))
    train_seasonal_errors = [
        demand[i - SEASONAL_LAG_HOURS] - demand[i] for i in train_indices
    ]
    if len(train_seasonal_errors) < 8:
        raise ValueError("At least 8 historical seasonal forecast errors are required")

    residual_mean = sum(train_seasonal_errors) / len(train_seasonal_errors)
    residual_variance = sum((e - residual_mean) ** 2 for e in train_seasonal_errors) / (
        len(train_seasonal_errors) - 1
    )
    residual_sigma = math.sqrt(residual_variance)

    actual = [demand[i] for i in test_indices]
    persistence = [demand[i - 1] for i in test_indices]
    seasonal = [demand[i - SEASONAL_LAG_HOURS] for i in test_indices]

    def interval_coverage(z_value: float) -> dict:
        covered = 0
        widths = []
        for observed, forecast in zip(actual, seasonal):
            lower = max(0.0, forecast - z_value * residual_sigma)
            upper = max(lower, forecast + z_value * residual_sigma)
            covered += int(lower <= observed <= upper)
            widths.append(upper - lower)
        return {
            "nominal_coverage": 0.90 if z_value == Z_90 else 0.95,
            "empirical_coverage": covered / len(actual),
            "mean_interval_width_m3_per_hour": sum(widths) / len(widths),
            "interval_method": "Gaussian residual approximation, lower bound clipped at zero",
        }

    predictions = []
    for i in test_indices:
        predictions.append({
            "timestamp": timestamps[i].isoformat(),
            "actual_water_demand_m3": demand[i],
            "persistence_forecast_m3": demand[i - 1],
            "seasonal_naive_24h_forecast_m3": demand[i - SEASONAL_LAG_HOURS],
            "seasonal_90pct_lower_m3": max(
                0.0, demand[i - SEASONAL_LAG_HOURS] - Z_90 * residual_sigma
            ),
            "seasonal_90pct_upper_m3": demand[i - SEASONAL_LAG_HOURS] + Z_90 * residual_sigma,
        })

    report = {
        "status": "baseline_evaluated",
        "target": "freshwater demand",
        "target_column": "water_demand_m3",
        "units": "m3 per hourly interval",
        "forecast_horizon_hours": 1,
        "input_csv": str(input_path),
        "row_count": len(demand),
        "history_rows": split,
        "test_rows": len(test_indices),
        "first_test_timestamp": timestamps[test_indices[0]].isoformat(),
        "last_test_timestamp": timestamps[test_indices[-1]].isoformat(),
        "forecasts": {
            "persistence": "Use the previous hour's measured demand.",
            "seasonal_naive_24h": "Use demand measured 24 hours before the target.",
        },
        "test_metrics": {
            "persistence": _metrics(actual, persistence),
            "seasonal_naive_24h": _metrics(actual, seasonal),
        },
        "distribution_diagnostics": {
            "observed_demand_test_window": _normality_diagnostic(actual),
            "seasonal_forecast_errors_on_training_history": _normality_diagnostic(
                train_seasonal_errors
            ),
            "note": (
                "Demand may be non-negative, seasonal, and affected by occupancy or weather. "
                "Do not assume it is Gaussian. Prediction intervals use training residual "
                "spread and must be judged by empirical holdout coverage."
            ),
        },
        "seasonal_prediction_intervals": {
            "training_residual_mean_m3_per_hour": residual_mean,
            "training_residual_standard_deviation_m3_per_hour": residual_sigma,
            "nominal_90pct": interval_coverage(Z_90),
            "nominal_95pct": interval_coverage(Z_95),
        },
        "test_predictions": predictions,
        "limitations": [
            "No measured data means no site-specific forecast skill can be established.",
            "This is a transparent statistical baseline, not deep learning or online learning.",
            "One-step forecasts do not yet model occupancy, holidays, weather, leakage, or outages.",
            "Gaussian intervals are a hypothesis checked by holdout coverage, not a guaranteed distribution.",
            "Use chronological holdouts; never randomly shuffle time-series rows for evaluation.",
        ],
    }

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly CSV with timestamp,water_demand_m3 columns")
    parser.add_argument("--output", default="build/water-demand-forecast/report.json")
    parser.add_argument("--test-fraction", type=float, default=0.25)
    args = parser.parse_args()
    report = evaluate_water_demand(args.input_csv, args.output, args.test_fraction)
    print(json.dumps({
        "status": report["status"],
        "history_rows": report["history_rows"],
        "test_rows": report["test_rows"],
        "test_metrics": report["test_metrics"],
        "distribution_diagnostics": report["distribution_diagnostics"],
        "seasonal_prediction_intervals": report["seasonal_prediction_intervals"],
        "output": str(args.output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
