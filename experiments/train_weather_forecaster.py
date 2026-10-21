"""Train and evaluate a small one-step-ahead weather regression baseline.

Input is the validated CSV emitted by experiments/forecasting_baselines.py.
The model is a transparent least-squares regression using timestamp cycles and
lagged observations. It is not a PV/wind power or island-demand forecast.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

LAGS = (1, 3, 24)


def _features(timestamp: str, values: list[float], index: int) -> list[float]:
    stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    hour = stamp.hour + stamp.minute / 60.0
    day_fraction = (stamp.timetuple().tm_yday - 1) / 366.0
    return [
        1.0,
        math.sin(2 * math.pi * hour / 24),
        math.cos(2 * math.pi * hour / 24),
        math.sin(2 * math.pi * day_fraction),
        math.cos(2 * math.pi * day_fraction),
        *[values[index - lag] for lag in LAGS],
    ]


def _metrics(actual: list[float], predicted: list[float]) -> dict:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metric inputs must be non-empty and equal length")
    errors = np.asarray(predicted, dtype=float) - np.asarray(actual, dtype=float)
    return {
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "bias_predicted_minus_actual": float(np.mean(errors)),
    }


def _fit_predict(timestamps: list[str], values: list[float],
                 train_indices: list[int], test_indices: list[int]) -> list[float]:
    if len(train_indices) < 8:
        raise ValueError("Need at least 8 training rows for regression")
    x_train = np.asarray([_features(timestamps[i], values, i) for i in train_indices], dtype=float)
    y_train = np.asarray([values[i] for i in train_indices], dtype=float)
    if not np.all(np.isfinite(x_train)) or not np.all(np.isfinite(y_train)):
        raise ValueError("Training data contain non-finite values")
    coefficients, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
    x_test = np.asarray([_features(timestamps[i], values, i) for i in test_indices], dtype=float)
    predictions = x_test @ coefficients
    if not np.all(np.isfinite(predictions)):
        raise ValueError("Model produced non-finite predictions")
    return predictions.tolist()


def train_and_evaluate(input_csv: str | Path, output_csv: str | Path) -> dict:
    input_path = Path(input_csv)
    metadata_path = Path(str(input_path) + ".metadata.json")
    if not metadata_path.exists():
        raise ValueError(f"Missing validated forecast metadata: {metadata_path}")
    source_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_utc", "actual", "split", "persistence_forecast", "seasonal_naive_24h_forecast"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)
    if not rows:
        raise ValueError("Input CSV contains no rows")

    timestamps = [row["timestamp_utc"] for row in rows]
    values = [float(row["actual"]) for row in rows]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Input contains non-finite target values")
    if any(rows[i]["split"] != "history" for i in range(next(
        (j for j, row in enumerate(rows) if row["split"] == "test"), len(rows)
    ))):
        raise ValueError("History rows must precede test rows")
    train_indices = [i for i, row in enumerate(rows) if row["split"] == "history"]
    test_indices = [i for i, row in enumerate(rows) if row["split"] == "test"]
    if not train_indices or not test_indices:
        raise ValueError("Input must contain non-empty history and test partitions")
    if train_indices != list(range(train_indices[0], train_indices[-1] + 1)):
        raise ValueError("History partition must be contiguous")
    if test_indices != list(range(test_indices[0], len(rows))):
        raise ValueError("Test partition must be a contiguous final holdout")

    predictions = _fit_predict(timestamps, values, train_indices, test_indices)
    actual = [values[i] for i in test_indices]
    persistence = [float(rows[i]["persistence_forecast"]) for i in test_indices]
    seasonal = [float(rows[i]["seasonal_naive_24h_forecast"]) for i in test_indices]
    model_metrics = _metrics(actual, predictions)
    baseline_metrics = {
        "persistence": _metrics(actual, persistence),
        "seasonal_naive_24h": _metrics(actual, seasonal),
    }
    best_baseline_mae = min(v["mae"] for v in baseline_metrics.values())
    skill = None if best_baseline_mae <= 1e-12 else 1.0 - model_metrics["mae"] / best_baseline_mae

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_by_index = dict(zip(test_indices, predictions))
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "timestamp_utc", "actual", "regression_forecast",
            "persistence_forecast", "seasonal_naive_24h_forecast",
        ])
        writer.writeheader()
        for i in test_indices:
            writer.writerow({
                "timestamp_utc": timestamps[i],
                "actual": values[i],
                "regression_forecast": prediction_by_index[i],
                "persistence_forecast": rows[i]["persistence_forecast"],
                "seasonal_naive_24h_forecast": rows[i]["seasonal_naive_24h_forecast"],
            })

    result = {
        "model": "ordinary least-squares regression",
        "features": ["intercept", "hour_sin", "hour_cos", "day_of_year_sin", "day_of_year_cos", "lag_1h", "lag_3h", "lag_24h"],
        "training_rows": len(train_indices),
        "test_rows": len(test_indices),
        "target": source_meta.get("target"),
        "target_units": source_meta.get("target_units"),
        "forecast_horizon_hours": 1,
        "test_metrics": {"regression": model_metrics, **baseline_metrics},
        "mae_skill_vs_best_baseline": skill,
        "skill_interpretation": "positive means lower MAE than the best simple baseline; negative means worse",
        "training_protocol": "fit once on the chronological history partition; evaluate the final holdout; lag features use only observations preceding each target",
        "upstream_input": str(input_path),
        "output_csv": str(output_path),
        "limitations": [
            "Forecasts a NASA POWER environmental parameter, not PV/wind output or island demand.",
            "One chronological holdout is not evidence of generalization across sites or seasons.",
            "Test-time lag features use earlier observed target values, representing rolling one-step-ahead forecasting.",
            "No hyperparameter tuning, uncertainty intervals, or field validation is included.",
        ],
    }
    Path(str(output_path) + ".metadata.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Validated CSV from forecasting_baselines.py")
    parser.add_argument("--output", default="data/processed/trained_weather_forecast.csv")
    args = parser.parse_args()
    try:
        result = train_and_evaluate(args.input_csv, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
