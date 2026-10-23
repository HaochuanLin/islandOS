"""Compare a small ML water-demand model with chronological naive baselines.

This is an optional scikit-learn experiment, not a deep-learning model or a
production forecasting service. It evaluates rolling one-hour-ahead forecasts:
past observed demand is available when forecasting the next hour, including
earlier observations in the held-out period. Future values are never features.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import sklearn

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from joblib import dump
except ImportError as exc:  # pragma: no cover - depends on optional installation
    raise SystemExit(
        "This experiment needs optional ML dependencies. Run: "
        "python -m pip install -r requirements-ml.txt"
    ) from exc

DAY_LAG_HOURS = 24
WEEK_LAG_HOURS = 168


def _load_series(input_csv: str | Path) -> tuple[list[datetime], list[float]]:
    path = Path(input_csv)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "water_demand_m3"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    if len(rows) <= WEEK_LAG_HOURS + 48:
        raise ValueError(
            "Need more than 216 hourly rows to build week-lag features and "
            "retain enough training samples."
        )

    timestamps: list[datetime] = []
    demand: list[float] = []
    for line, row in enumerate(rows, start=2):
        raw_timestamp = (row.get("timestamp") or "").strip()
        try:
            stamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp at CSV line {line}: {raw_timestamp!r}") from exc
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError(f"timestamp must include a timezone offset at CSV line {line}")
        if timestamps and (stamp - timestamps[-1]).total_seconds() != 3600:
            raise ValueError(f"Expected continuous hourly timestamps at CSV line {line}")

        raw_value = (row.get("water_demand_m3") or "").strip()
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"Invalid water_demand_m3 at CSV line {line}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(
                f"water_demand_m3 must be finite and non-negative at CSV line {line}"
            )
        timestamps.append(stamp)
        demand.append(value)

    return timestamps, demand


def _features(index: int, timestamps: list[datetime], demand: list[float]) -> list[float]:
    stamp = timestamps[index]
    recent = demand[index - DAY_LAG_HOURS:index]
    hour_angle = 2.0 * math.pi * stamp.hour / 24.0
    weekday_angle = 2.0 * math.pi * stamp.weekday() / 7.0
    return [
        demand[index - 1],
        demand[index - DAY_LAG_HOURS],
        demand[index - WEEK_LAG_HOURS],
        sum(recent) / DAY_LAG_HOURS,
        math.sin(hour_angle),
        math.cos(hour_angle),
        math.sin(weekday_angle),
        math.cos(weekday_angle),
    ]


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metric inputs must be non-empty and aligned")
    errors = [prediction - observation for observation, prediction in zip(actual, predicted)]
    return {
        "mae_m3_per_hour": sum(abs(error) for error in errors) / len(errors),
        "rmse_m3_per_hour": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_predicted_minus_actual_m3_per_hour": sum(errors) / len(errors),
    }


def compare_water_demand_models(
    input_csv: str | Path,
    output_json: str | Path,
    train_fraction: float = 0.70,
    model_output: str | Path | None = None,
) -> dict[str, Any]:
    """Train once on earlier rows and compare forecasts on a later time window."""
    if not 0.60 <= train_fraction <= 0.85:
        raise ValueError("train_fraction must be between 0.60 and 0.85")

    timestamps, demand = _load_series(input_csv)
    split = int(len(demand) * train_fraction)
    train_indices = list(range(WEEK_LAG_HOURS, split))
    test_indices = list(range(split, len(demand)))
    if len(train_indices) < 48:
        raise ValueError("Not enough training samples after week-lag feature construction")
    if len(test_indices) < 24:
        raise ValueError("Not enough held-out samples for a meaningful comparison")

    x_train = [_features(i, timestamps, demand) for i in train_indices]
    y_train = [demand[i] for i in train_indices]
    x_test = [_features(i, timestamps, demand) for i in test_indices]
    actual = [demand[i] for i in test_indices]

    model = HistGradientBoostingRegressor(
        learning_rate=0.08,
        max_iter=120,
        max_leaf_nodes=15,
        l2_regularization=1.0,
        random_state=2026,
    )
    model.fit(x_train, y_train)
    ml_predictions = [max(0.0, float(value)) for value in model.predict(x_test)]

    prediction_sets = {
        "persistence_previous_hour": [demand[i - 1] for i in test_indices],
        "seasonal_naive_previous_day": [demand[i - DAY_LAG_HOURS] for i in test_indices],
        "seasonal_naive_previous_week": [demand[i - WEEK_LAG_HOURS] for i in test_indices],
        "hist_gradient_boosting": ml_predictions,
    }
    metrics = {
        name: _metrics(actual, predictions)
        for name, predictions in prediction_sets.items()
    }
    best_mae_model = min(metrics, key=lambda name: metrics[name]["mae_m3_per_hour"])

    report: dict[str, Any] = {
        "status": "models_compared",
        "input_csv": Path(input_csv).name,
        "input_csv_sha256": hashlib.sha256(Path(input_csv).read_bytes()).hexdigest(),
        "target": "freshwater demand",
        "target_column": "water_demand_m3",
        "units": "m3 per hourly interval",
        "forecast_horizon_hours": 1,
        "forecast_protocol": (
            "rolling one-step-ahead; each prediction uses observations available "
            "before its target hour, including earlier observed test-window demand"
        ),
        "chronological_split": {
            "train_fraction": train_fraction,
            "split_index": split,
            "training_samples": len(train_indices),
            "test_samples": len(test_indices),
            "train_start": timestamps[train_indices[0]].isoformat(),
            "train_end": timestamps[train_indices[-1]].isoformat(),
            "test_start": timestamps[test_indices[0]].isoformat(),
            "test_end": timestamps[test_indices[-1]].isoformat(),
        },
        "model": {
            "name": "HistGradientBoostingRegressor",
            "library": "scikit-learn",
            "library_version": sklearn.__version__,
            "random_state": 2026,
            "features": [
                "previous-hour demand",
                "same-hour previous-day demand",
                "same-hour previous-week demand",
                "mean demand over previous 24 hours",
                "hour-of-day sine/cosine",
                "day-of-week sine/cosine",
            ],
            "training_rows_end_before_test_window": split,
        },
        "test_metrics": metrics,
        "lowest_mae_model_on_this_holdout": best_mae_model,
        "interpretation": (
            "This ranking applies only to this dataset and holdout. Do not select "
            "a model from one score alone; inspect RMSE, bias, seasonal periods, "
            "and repeat chronological evaluation on other time windows."
        ),
        "forecast_rows": [
            {
                "timestamp": timestamps[index].isoformat(),
                "actual_water_demand_m3": actual[position],
                **{
                    name: predictions[position]
                    for name, predictions in prediction_sets.items()
                },
            }
            for position, index in enumerate(test_indices)
        ],
        "limitations": [
            "This is a small gradient-boosting model, not deep learning or online learning.",
            "One-step evaluation assumes the previous hour's measured demand becomes available before the next forecast.",
            "No weather, occupancy, holiday, leak, or plant-operation features are included.",
            "Public rural German reservoir data is not island-specific and is not desalination production data.",
            "A better demand forecast does not by itself prove better energy dispatch or lower operating cost.",
        ],
    }

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if model_output is not None:
        model_path = Path(model_output)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        dump(model, model_path)
        report["model_artifact"] = str(model_path)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly CSV with timestamp,water_demand_m3 columns")
    parser.add_argument("--output", default="build/water-demand-forecast/model-comparison.json")
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--model-output", help="Optional path to save the trained scikit-learn model")
    args = parser.parse_args()
    report = compare_water_demand_models(
        args.input_csv,
        args.output,
        train_fraction=args.train_fraction,
        model_output=args.model_output,
    )
    print(json.dumps({
        "status": report["status"],
        "training_samples": report["chronological_split"]["training_samples"],
        "test_samples": report["chronological_split"]["test_samples"],
        "test_metrics": report["test_metrics"],
        "lowest_mae_model_on_this_holdout": report["lowest_mae_model_on_this_holdout"],
        "output": str(args.output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
