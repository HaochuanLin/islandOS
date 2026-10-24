"""Run a trusted IslandOS forecast plugin as a rolling-origin backtest.

The plugin is loaded from a local Python module (module:Class), so only import
code you trust. Each prediction receives historical observations only; the
report is compatible with build_forecast_dispatch_input.py.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from islandos_core.forecasting import ForecastModelRegistry, ForecastRequest, WaterObservation

def _timestamp(raw: str, line: int) -> datetime:
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp at CSV line {line}: {raw!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"Timestamp must include a timezone at CSV line {line}")
    return stamp.astimezone(timezone.utc)

def _load_series(path: str | Path) -> tuple[list[datetime], list[float]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        duplicates = sorted({name for name in headers if headers.count(name) > 1})
        if duplicates:
            raise ValueError("Input CSV has duplicate columns: " + ", ".join(duplicates))
        missing = {"timestamp", "water_demand_m3"} - set(headers)
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)
    for line, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(f"Input CSV has extra fields at CSV line {line}")
    if len(rows) < 2:
        raise ValueError("Input CSV must contain at least two hourly observations")
    timestamps, values = [], []
    for line, row in enumerate(rows, start=2):
        stamp = _timestamp(row.get("timestamp") or "", line)
        try:
            value = float(row.get("water_demand_m3") or "")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid water_demand_m3 at CSV line {line}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"water_demand_m3 must be finite and non-negative at CSV line {line}")
        if timestamps and (stamp - timestamps[-1]).total_seconds() != 3600:
            raise ValueError(f"Input must contain strictly ordered, continuous hourly rows at CSV line {line}")
        timestamps.append(stamp)
        values.append(value)
    return timestamps, values

def load_plugin(specification: str) -> Any:
    """Load a no-argument plugin class from a trusted module:Class spec."""
    if ":" not in specification:
        raise ValueError("Plugin must be specified as module:Class")
    module_name, class_name = specification.split(":", 1)
    if not module_name or not class_name:
        raise ValueError("Plugin must be specified as module:Class")
    try:
        module = importlib.import_module(module_name)
        plugin_class = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"Cannot import plugin {specification!r}: {exc}") from exc
    if not isinstance(plugin_class, type):
        raise ValueError(f"Plugin target {specification!r} must be a class")
    try:
        return plugin_class()
    except Exception as exc:
        raise ValueError(f"Could not instantiate plugin {specification!r}: {exc}") from exc

def backtest_plugin(input_csv: str | Path, plugin: Any, output_json: str | Path, *,
                    test_fraction: float = 0.2, history_hours: int = 168) -> dict[str, Any]:
    """Generate strict one-step rolling-origin predictions and a dispatch-ready report."""
    if not math.isfinite(test_fraction) or not 0 < test_fraction < 0.5:
        raise ValueError("test_fraction must be greater than 0 and less than 0.5")
    if isinstance(history_hours, bool) or not isinstance(history_hours, int) or history_hours < 1:
        raise ValueError("history_hours must be a positive integer")
    timestamps, values = _load_series(input_csv)
    split = max(history_hours, int(len(values) * (1 - test_fraction)))
    if split >= len(values):
        raise ValueError(f"Need more than {history_hours} rows and at least one test row; found {len(values)}")
    registry = ForecastModelRegistry()
    registry.register(plugin)
    rows, actuals, predictions = [], [], []
    persistence_actuals, persistence_predictions = [], []
    seasonal_actuals, seasonal_predictions = [], []
    for index in range(split, len(values)):
        start = max(0, index - history_hours)
        history = tuple(WaterObservation(timestamps[j], values[j]) for j in range(start, index))
        request = ForecastRequest(history=history, target_timestamps=(timestamps[index],))
        result = registry.forecast(plugin.model_id, request)
        predicted, actual = result.points[0].predicted_demand_m3, values[index]
        persistence = values[index - 1]
        # Only score the 24-hour seasonal baseline where the corresponding
        # prior-day observation exists; do not silently substitute another lag.
        seasonal = values[index - 24] if index >= 24 else None
        rows.append({
            "timestamp": timestamps[index].isoformat().replace("+00:00", "Z"),
            "actual_water_demand_m3": actual,
            "plugin_forecast_m3": predicted,
            "persistence_baseline_m3": persistence,
            "seasonal_24h_baseline_m3": seasonal,
            "fold": 0,
        })
        actuals.append(actual)
        predictions.append(predicted)
        persistence_actuals.append(actual)
        persistence_predictions.append(persistence)
        if seasonal is not None:
            seasonal_actuals.append(actual)
            seasonal_predictions.append(seasonal)
    errors = [prediction - actual for actual, prediction in zip(actuals, predictions)]

    def summarize(actual_series: list[float], forecast_series: list[float]) -> dict[str, float | int]:
        baseline_errors = [forecast - actual for actual, forecast in zip(actual_series, forecast_series)]
        return {
            "samples": len(baseline_errors),
            "mae_m3_per_hour": mean(abs(error) for error in baseline_errors),
            "rmse_m3_per_hour": math.sqrt(mean(error * error for error in baseline_errors)),
            "bias_predicted_minus_actual_m3_per_hour": mean(baseline_errors),
            "underforecast_rate": sum(error < 0 for error in baseline_errors) / len(baseline_errors),
        }

    model_metrics = summarize(actuals, predictions)
    persistence_metrics = summarize(persistence_actuals, persistence_predictions)
    seasonal_metrics = summarize(seasonal_actuals, seasonal_predictions) if seasonal_actuals else None
    persistence_mae = persistence_metrics["mae_m3_per_hour"]
    skill_vs_persistence = (
        1.0 - model_metrics["mae_m3_per_hour"] / persistence_mae
        if persistence_mae > 0 else None
    )

    # Compare seasonal naive and plugin on exactly the same timestamps. The
    # full plugin test window can be longer than the seasonal baseline window.
    seasonal_rows = [row for row in rows if row["seasonal_24h_baseline_m3"] is not None]
    plugin_on_seasonal_window = summarize(
        [row["actual_water_demand_m3"] for row in seasonal_rows],
        [row["plugin_forecast_m3"] for row in seasonal_rows],
    ) if seasonal_rows else None
    seasonal_skill = None
    if seasonal_metrics is not None and plugin_on_seasonal_window is not None:
        seasonal_mae = seasonal_metrics["mae_m3_per_hour"]
        if seasonal_mae > 0:
            seasonal_skill = 1.0 - plugin_on_seasonal_window["mae_m3_per_hour"] / seasonal_mae
    report = {
        "status": "rolling_backtest_completed",
        "model_family": "IslandOS forecast plugin",
        "model_id": plugin.model_id,
        "model_version": plugin.version,
        "plugin_forecast_column": "plugin_forecast_m3",
        "input_csv": str(input_csv),
        "input_csv_sha256": hashlib.sha256(Path(input_csv).read_bytes()).hexdigest(),
        "python_version": sys.version.split()[0],
        "training": {
            "history_rows_before_test": split,
            "rolling_history_hours": history_hours,
            "test_start_timestamp": timestamps[split].isoformat().replace("+00:00", "Z"),
            "test_samples": len(rows),
            "one_step_ahead": True,
            "only_prior_observations_passed_to_plugin": True,
        },
        "test_metrics": model_metrics,
        "baseline_metrics": {
            "persistence_last_observation": persistence_metrics,
            "seasonal_naive_24h": seasonal_metrics,
        },
        "skill_vs_persistence_mae": skill_vs_persistence,
        "seasonal_comparable_plugin_metrics": plugin_on_seasonal_window,
        "skill_vs_seasonal_naive_24h_mae": seasonal_skill,
        "skill_score_interpretation": "positive means plugin MAE is lower than the named baseline; negative means worse; null means the baseline MAE is zero or no comparable seasonal window exists",
        "forecast_rows": rows,
        "limitations": [
            "Only prior observations are passed to each prediction; this is a rolling-origin one-step backtest.",
            "The plugin code is imported and executed locally; only load code you trust.",
            "A successful report proves interface compatibility, not predictive skill or site suitability.",
            "The report must be paired with power/dispatch data from the same site and timestamps.",
            "No online learning, live control, or automatic model promotion is performed.",
        ],
    }
    output = Path(output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly CSV with timestamp and water_demand_m3 columns")
    parser.add_argument("--plugin", required=True, help="Trusted no-argument plugin class as module:Class")
    parser.add_argument("--output", default="build/plugin-backtest/forecast_report.json")
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--history-hours", type=int, default=168)
    args = parser.parse_args()
    try:
        plugin = load_plugin(args.plugin)
        report = backtest_plugin(args.input_csv, plugin, args.output,
                                 test_fraction=args.test_fraction, history_hours=args.history_hours)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": report["status"], "model_id": report["model_id"],
        "model_version": report["model_version"],
        "test_samples": report["training"]["test_samples"],
        "mae_m3_per_hour": report["test_metrics"]["mae_m3_per_hour"],
        "report": args.output,
    }, indent=2))

if __name__ == "__main__":
    main()
