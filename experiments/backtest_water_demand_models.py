"""Repeated expanding-window backtest for water-demand forecasting models.

Unlike a single chronological holdout, this experiment refits each model at
several historical cutoffs. Each forecast is one hour ahead and uses only
observations available before its target hour. This is still an offline
evaluation, not online learning or proof of transfer to an island.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
except ImportError as exc:  # pragma: no cover - depends on optional installation
    raise SystemExit(
        "This experiment needs optional ML dependencies. Run: "
        "python -m pip install -r requirements-ml.txt"
    ) from exc

from experiments.compare_water_demand_models import (
    DAY_LAG_HOURS,
    WEEK_LAG_HOURS,
    _features,
    _load_series,
    _metrics,
)


def backtest_water_demand_models(
    input_csv: str | Path,
    output_json: str | Path,
    initial_train_fraction: float = 0.65,
    test_window_hours: int = 24,
    step_hours: int = 24,
    max_folds: int = 8,
) -> dict[str, Any]:
    """Evaluate baseline and ML forecasts over repeated chronological windows."""
    if not 0.60 <= initial_train_fraction <= 0.85:
        raise ValueError("initial_train_fraction must be between 0.60 and 0.85")
    if test_window_hours < 24:
        raise ValueError("test_window_hours must be at least 24")
    if step_hours < test_window_hours:
        raise ValueError("step_hours must be at least test_window_hours to avoid overlap")
    if max_folds < 2:
        raise ValueError("max_folds must be at least 2 to compare multiple time windows")

    timestamps, demand = _load_series(input_csv)
    initial_cutoff = int(len(demand) * initial_train_fraction)
    if initial_cutoff - WEEK_LAG_HOURS < 48:
        raise ValueError("Not enough training samples after week-lag feature construction")

    available_fold_starts = list(
        range(initial_cutoff, len(demand) - test_window_hours + 1, step_hours)
    )
    if not available_fold_starts:
        raise ValueError(
            "No complete test windows remain; reduce the initial training fraction "
            "or test-window length, or provide more data"
        )

    # Long datasets can contain thousands of possible hourly/daily folds. Sample
    # evenly across the available period so the backtest remains tractable and
    # does not silently evaluate only the earliest or latest few windows.
    if len(available_fold_starts) > max_folds:
        selected_positions = [
            round(index * (len(available_fold_starts) - 1) / (max_folds - 1))
            for index in range(max_folds)
        ]
        fold_starts = [available_fold_starts[position] for position in selected_positions]
    else:
        fold_starts = available_fold_starts

    model_names = (
        "persistence_previous_hour",
        "seasonal_naive_previous_day",
        "seasonal_naive_previous_week",
        "hist_gradient_boosting",
    )
    aggregate_actual: list[float] = []
    aggregate_predictions: dict[str, list[float]] = {name: [] for name in model_names}
    folds: list[dict[str, Any]] = []
    forecast_rows: list[dict[str, Any]] = []

    for fold_number, cutoff in enumerate(fold_starts, start=1):
        train_indices = list(range(WEEK_LAG_HOURS, cutoff))
        test_indices = list(range(cutoff, cutoff + test_window_hours))
        x_train = [_features(i, timestamps, demand) for i in train_indices]
        y_train = [demand[i] for i in train_indices]
        x_test = [_features(i, timestamps, demand) for i in test_indices]

        model = HistGradientBoostingRegressor(
            learning_rate=0.08,
            max_iter=120,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=2026,
        )
        model.fit(x_train, y_train)
        predictions: dict[str, list[float]] = {
            "persistence_previous_hour": [demand[i - 1] for i in test_indices],
            "seasonal_naive_previous_day": [
                demand[i - DAY_LAG_HOURS] for i in test_indices
            ],
            "seasonal_naive_previous_week": [
                demand[i - WEEK_LAG_HOURS] for i in test_indices
            ],
            "hist_gradient_boosting": [
                max(0.0, float(value)) for value in model.predict(x_test)
            ],
        }
        actual = [demand[i] for i in test_indices]
        fold_metrics = {
            name: _metrics(actual, values) for name, values in predictions.items()
        }
        folds.append({
            "fold": fold_number,
            "training_rows": len(train_indices),
            "training_end": timestamps[cutoff - 1].isoformat(),
            "test_start": timestamps[test_indices[0]].isoformat(),
            "test_end": timestamps[test_indices[-1]].isoformat(),
            "test_rows": len(test_indices),
            "metrics": fold_metrics,
        })
        aggregate_actual.extend(actual)
        for name, values in predictions.items():
            aggregate_predictions[name].extend(values)
        for position, index in enumerate(test_indices):
            forecast_rows.append({
                "fold": fold_number,
                "timestamp": timestamps[index].isoformat(),
                "actual_water_demand_m3": actual[position],
                **{
                    name: values[position]
                    for name, values in predictions.items()
                },
            })

    aggregate_metrics = {
        name: _metrics(aggregate_actual, values)
        for name, values in aggregate_predictions.items()
    }
    report: dict[str, Any] = {
        "status": "rolling_backtest_completed",
        "input_csv": Path(input_csv).name,
        "target": "freshwater demand",
        "target_column": "water_demand_m3",
        "units": "m3 per hourly interval",
        "forecast_horizon_hours": 1,
        "protocol": (
            "expanding-window backtest; each fold trains only on rows before its "
            "cutoff; one-step forecasts use only lagged observations; test windows "
            "do not overlap"
        ),
        "configuration": {
            "initial_train_fraction": initial_train_fraction,
            "initial_training_cutoff_index": initial_cutoff,
            "test_window_hours": test_window_hours,
            "step_hours": step_hours,
            "available_fold_count": len(available_fold_starts),
            "max_folds": max_folds,
            "fold_count": len(folds),
            "evaluated_hours": len(aggregate_actual),
        },
        "aggregate_metrics": aggregate_metrics,
        "folds": folds,
        "forecast_rows": forecast_rows,
        "limitations": [
            "Repeated windows are stronger than a single split but do not prove transfer to another site or season.",
            "The machine-learning model is gradient boosting, not deep learning or online learning.",
            "The evaluation is one-step-ahead and assumes each previous-hour measurement is available before the next forecast.",
            "No weather, occupancy, holiday, leakage, or plant-operation features are included.",
            "Synthetic results verify software behavior only and are not evidence of real-world forecasting skill.",
        ],
    }

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly CSV with timestamp,water_demand_m3 columns")
    parser.add_argument("--output", default="build/water-demand-forecast/rolling-backtest.json")
    parser.add_argument("--initial-train-fraction", type=float, default=0.65)
    parser.add_argument("--test-window-hours", type=int, default=24)
    parser.add_argument("--step-hours", type=int, default=24)
    parser.add_argument("--max-folds", type=int, default=8, help="Maximum number of evenly spaced test windows")
    args = parser.parse_args()
    report = backtest_water_demand_models(
        args.input_csv,
        args.output,
        initial_train_fraction=args.initial_train_fraction,
        test_window_hours=args.test_window_hours,
        step_hours=args.step_hours,
        max_folds=args.max_folds,
    )
    print(json.dumps({
        "status": report["status"],
        "configuration": report["configuration"],
        "aggregate_metrics": report["aggregate_metrics"],
        "output": str(args.output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
