"""Evaluate simple one-hour-ahead weather-parameter forecasting baselines.

This is a forecasting-methodology prototype, not a renewable-power forecast.
It evaluates NASA POWER environmental observations only and never fabricates
PV/wind generation or island demand.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

DEFAULT_TARGET = "ALLSKY_SFC_SW_DWN"
SEASONAL_LAG_HOURS = 24


def _timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp_utc: {value!r}") from exc
    if result.tzinfo is None:
        raise ValueError("timestamp_utc must include a timezone")
    return result


def _metric_summary(actual: list[float], predicted: list[float]) -> dict:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metric inputs must be non-empty and have equal length")
    errors = [p - a for a, p in zip(actual, predicted)]
    return {
        "mae": sum(abs(e) for e in errors) / len(errors),
        "rmse": math.sqrt(sum(e * e for e in errors) / len(errors)),
        "bias_predicted_minus_actual": sum(errors) / len(errors),
    }


def evaluate_baselines(input_csv: str | Path, output_csv: str | Path,
                       target: str = DEFAULT_TARGET,
                       test_fraction: float = 0.30) -> dict:
    if not 0.05 <= test_fraction <= 0.50:
        raise ValueError("test_fraction must be between 0.05 and 0.50")
    input_path = Path(input_csv)
    sidecar_path = input_path.with_suffix(input_path.suffix + ".metadata.json")
    if not sidecar_path.exists():
        raise ValueError(f"Missing provenance sidecar: {sidecar_path}")
    source_metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    source_parameters = source_metadata.get("response_metadata", {}).get("parameters", {})
    if target not in source_parameters or not source_parameters[target].get("units"):
        raise ValueError(f"Source metadata must declare units for target {target}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_utc", target}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        raw = list(reader)
    if len(raw) < SEASONAL_LAG_HOURS + 10:
        raise ValueError(f"Need at least {SEASONAL_LAG_HOURS + 10} hourly rows")

    timestamps: list[datetime] = []
    values: list[float] = []
    for line, row in enumerate(raw, start=2):
        stamp = _timestamp(row["timestamp_utc"])
        if timestamps and (stamp - timestamps[-1]).total_seconds() != 3600:
            raise ValueError(f"Expected continuous ordered hourly records at line {line}")
        raw_value = (row.get(target) or "").strip()
        if not raw_value:
            raise ValueError(f"Missing {target} at {row['timestamp_utc']}; no imputation performed")
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"Non-numeric {target} at {row['timestamp_utc']}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Non-finite {target} at {row['timestamp_utc']}")
        timestamps.append(stamp)
        values.append(value)

    # A forecast row at t predicts y[t] using y[t-1] (persistence) or y[t-24]
    # (seasonal naive). These are prior observations, never future targets.
    first_target_index = SEASONAL_LAG_HOURS
    prediction_indices = list(range(first_target_index, len(values)))
    if len(prediction_indices) < 10:
        raise ValueError("Not enough eligible target rows after seasonal warm-up")
    split_position = int(len(prediction_indices) * (1.0 - test_fraction))
    if split_position < 1 or split_position >= len(prediction_indices):
        raise ValueError("Chronological split leaves an empty train or test set")
    train_indices = prediction_indices[:split_position]
    test_indices = prediction_indices[split_position:]

    train_index_set = set(train_indices)
    output_rows = []
    for i in prediction_indices:
        output_rows.append({
            "timestamp_utc": timestamps[i].isoformat().replace("+00:00", "Z"),
            "actual": values[i],
            "persistence_forecast": values[i - 1],
            "seasonal_naive_24h_forecast": values[i - SEASONAL_LAG_HOURS],
            "split": "history" if i in train_index_set else "test",
        })

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "timestamp_utc", "actual", "persistence_forecast",
            "seasonal_naive_24h_forecast", "split",
        ])
        writer.writeheader()
        writer.writerows(output_rows)

    def collect(indices: list[int], predictor) -> tuple[list[float], list[float]]:
        return [values[i] for i in indices], [predictor(i) for i in indices]

    persistence_actual, persistence_pred = collect(test_indices, lambda i: values[i - 1])
    seasonal_actual, seasonal_pred = collect(
        test_indices, lambda i: values[i - SEASONAL_LAG_HOURS]
    )
    result = {
        "source": "NASA POWER hourly environmental observations",
        "target": target,
        "target_units": source_parameters[target]["units"],
        "forecast_horizon_hours": 1,
        "baselines": {
            "persistence": "predict next-hour value using the most recent observation",
            "seasonal_naive_24h": "predict using the observation 24 hours before the target",
        },
        "input_csv": str(input_path),
        "output_csv": str(output_path),
        "output_rows": len(output_rows),
        "history_rows_before_test": len(train_indices),
        "test_rows": len(test_indices),
        "first_test_timestamp_utc": timestamps[test_indices[0]].isoformat().replace("+00:00", "Z"),
        "last_test_timestamp_utc": timestamps[test_indices[-1]].isoformat().replace("+00:00", "Z"),
        "test_metrics": {
            "persistence": _metric_summary(persistence_actual, persistence_pred),
            "seasonal_naive_24h": _metric_summary(seasonal_actual, seasonal_pred),
        },
        "limitations": [
            "This predicts a NASA POWER weather parameter, not PV/wind electrical output or island demand.",
            "The chronological holdout is a simple single split, not rolling-origin cross-validation.",
            "The baselines use prior observations only; no trained model is fitted.",
            "Metrics are site- and period-dependent and do not establish real-world operational value.",
            "Input data are gridded environmental data, not site-metered measurements.",
        ],
    }
    Path(str(output_path) + ".metadata.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Raw NASA POWER hourly CSV")
    parser.add_argument("--output", default="data/processed/forecast_baselines.csv")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--test-fraction", type=float, default=0.30)
    args = parser.parse_args()
    try:
        result = evaluate_baselines(args.input_csv, args.output, args.target, args.test_fraction)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
