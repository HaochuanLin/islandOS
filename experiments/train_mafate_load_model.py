"""Train and chronologically evaluate a one-step-ahead Mafate household-load model.

The input is the normalized microgrid_hourly.csv produced by
import_mafate_microgrid_data.py. The test window is evaluated as a rolling
one-step-ahead forecast: actual observations from earlier test hours may be
used as lag features, but never the target hour or future observations.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from joblib import dump
except ImportError as exc:  # pragma: no cover - exercised in clean installs
    raise SystemExit(
        "This experiment needs the optional ML dependencies. Run: "
        "python -m pip install -r requirements-ml.txt"
    ) from exc

WEEK_LAG_HOURS = 168
DAY_LAG_HOURS = 24


def _parse_timestamp(value: str, line: int) -> datetime:
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp_local at CSV line {line}: {value!r}") from exc


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metrics require non-empty, aligned actual and predicted values")
    errors = [prediction - observation for observation, prediction in zip(actual, predicted)]
    return {
        "mae_kw": sum(abs(error) for error in errors) / len(errors),
        "rmse_kw": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_predicted_minus_actual_kw": sum(errors) / len(errors),
    }


def _load_series(path: str | Path, target: str) -> tuple[list[datetime], list[float | None]]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_local", target}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    # A week-lag feature requires 168 prior observations. The number of rows
    # needed for a valid chronological train/test split is larger and depends on
    # train_fraction, missing values, and the minimum sample counts checked below.
    if len(rows) <= WEEK_LAG_HOURS:
        raise ValueError(
            "Need at least 169 hourly rows to construct week-lag features; "
            "a valid chronological train/test evaluation requires substantially more."
        )

    timestamps: list[datetime] = []
    values: list[float | None] = []
    timezone_modes = set()
    for line, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp_local") or "", line)
        timezone_modes.add(stamp.tzinfo is not None and stamp.utcoffset() is not None)
        if len(timezone_modes) > 1:
            raise ValueError("Input mixes timezone-aware and timezone-naive timestamps")
        if timestamps and (stamp - timestamps[-1]).total_seconds() != 3600:
            raise ValueError(f"Expected continuous hourly timestamps at CSV line {line}")
        raw = (row.get(target) or "").strip()
        if not raw:
            value = None
        else:
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError(f"Invalid {target} at CSV line {line}") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{target} must be finite and non-negative at CSV line {line}")
        timestamps.append(stamp)
        values.append(value)
    return timestamps, values


def _features(index: int, timestamps: list[datetime],
              values: list[float | None]) -> list[float] | None:
    recent = values[index - DAY_LAG_HOURS:index]
    lag_1, lag_24, lag_168 = values[index - 1], values[index - 24], values[index - 168]
    if lag_1 is None or lag_24 is None or lag_168 is None or any(v is None for v in recent):
        return None
    stamp = timestamps[index]
    hour_angle = 2 * math.pi * stamp.hour / 24
    weekday_angle = 2 * math.pi * stamp.weekday() / 7
    rolling_mean_24 = sum(recent) / DAY_LAG_HOURS
    return [
        float(lag_1), float(lag_24), float(lag_168), rolling_mean_24,
        math.sin(hour_angle), math.cos(hour_angle),
        math.sin(weekday_angle), math.cos(weekday_angle),
    ]


def train_and_evaluate(input_csv: str | Path, output_json: str | Path,
                       target: str = "house_1_load_kw",
                       model_output: str | Path | None = None,
                       train_fraction: float = 0.70) -> dict[str, Any]:
    if not 0.60 <= train_fraction <= 0.85:
        raise ValueError("train_fraction must be between 0.60 and 0.85")
    timestamps, values = _load_series(input_csv, target)
    split = int(len(values) * train_fraction)

    train_indices = [
        i for i in range(WEEK_LAG_HOURS, split)
        if values[i] is not None and _features(i, timestamps, values) is not None
    ]
    test_indices = [
        i for i in range(split, len(values))
        if values[i] is not None and _features(i, timestamps, values) is not None
    ]
    if len(train_indices) < 48:
        raise ValueError("Not enough complete training samples after lag/missing-data checks")
    if len(test_indices) < 24:
        raise ValueError("Not enough complete test samples after lag/missing-data checks")

    x_train = [_features(i, timestamps, values) for i in train_indices]
    y_train = [float(values[i]) for i in train_indices]
    x_test = [_features(i, timestamps, values) for i in test_indices]
    actual = [float(values[i]) for i in test_indices]

    model = HistGradientBoostingRegressor(
        learning_rate=0.08,
        max_iter=150,
        max_leaf_nodes=15,
        l2_regularization=1.0,
        random_state=2026,
    )
    model.fit(x_train, y_train)
    ml_predictions = [max(0.0, float(value)) for value in model.predict(x_test)]

    prediction_sets = {
        "persistence_lag_1h": [float(values[i - 1]) for i in test_indices],
        "seasonal_naive_lag_24h": [float(values[i - 24]) for i in test_indices],
        "seasonal_naive_lag_168h": [float(values[i - 168]) for i in test_indices],
        "hist_gradient_boosting": ml_predictions,
    }
    report: dict[str, Any] = {
        "status": "trained_and_evaluated",
        "input_csv": Path(input_csv).name,
        "target_column": target,
        "target_unit": "kW",
        "forecast_protocol": "rolling_one_step_ahead",
        "chronological_split": {
            "train_fraction": train_fraction,
            "split_index": split,
            "training_samples": len(train_indices),
            "test_samples": len(test_indices),
            "excluded_rows_due_to_missing_target_or_lag_history": (
                len(values) - split - len(test_indices)
            ),
            "train_start": timestamps[train_indices[0]].isoformat(),
            "train_end": timestamps[train_indices[-1]].isoformat(),
            "test_start": timestamps[test_indices[0]].isoformat(),
            "test_end": timestamps[test_indices[-1]].isoformat(),
        },
        "features": [
            "previous hour load", "same hour previous day", "same hour previous week",
            "mean load over previous 24 hours", "hour-of-day sine/cosine",
            "day-of-week sine/cosine",
        ],
        "test_metrics": {
            name: _metrics(actual, predictions)
            for name, predictions in prediction_sets.items()
        },
        "forecast_rows": [
            {
                "timestamp_local": timestamps[index].isoformat(),
                "actual_kw": actual_value,
                **{name: predictions[position]
                   for name, predictions in prediction_sets.items()},
            }
            for position, (index, actual_value) in enumerate(zip(test_indices, actual))
        ],
        "limitations": [
            "This is a real-data workflow, but the report only represents the input dataset actually supplied by the user.",
            "The split is chronological. Each test forecast uses earlier observed loads as lag features; this is one-step-ahead evaluation, not a 24-hour-ahead multi-step forecast.",
            "HistGradientBoostingRegressor is compared against transparent persistence and seasonal baselines; it is not assumed to win.",
            "The model uses load history and calendar features only, not weather forecasts.",
            "Results from three homes at one experimental microgrid do not establish performance for other islands.",
            "This dataset has no water-demand or desalination-production target.",
        ],
    }

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if model_output is not None:
        model_path = Path(model_output)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        dump(model, model_path)
        report["model_artifact"] = str(model_path)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Normalized microgrid_hourly.csv")
    parser.add_argument("--target", default="house_1_load_kw",
                        choices=("house_1_load_kw", "house_2_load_kw", "house_3_load_kw"))
    parser.add_argument("--output", required=True, help="JSON evaluation report path")
    parser.add_argument("--model-output", help="Optional path to save the trained scikit-learn model")
    parser.add_argument("--train-fraction", type=float, default=0.70)
    args = parser.parse_args()
    report = train_and_evaluate(
        args.input_csv, args.output, args.target, args.model_output, args.train_fraction
    )
    print(json.dumps({
        "status": report["status"],
        "target_column": report["target_column"],
        "training_samples": report["chronological_split"]["training_samples"],
        "test_samples": report["chronological_split"]["test_samples"],
        "test_metrics": report["test_metrics"],
        "report_path": args.output,
        "model_artifact": report.get("model_artifact"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
