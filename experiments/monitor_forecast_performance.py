"""Monitor chronological water-demand forecast errors after actuals arrive.

Input CSV columns:
  timestamp,actual_water_demand_m3,forecast_water_demand_m3

This tool detects a possible change in forecast error. It does not retrain a
model automatically, and a warning is a review signal rather than proof of
statistical drift.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = (
    "timestamp",
    "actual_water_demand_m3",
    "forecast_water_demand_m3",
)


def _parse_timestamp(raw: str, line: int) -> datetime:
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp at CSV line {line}: {raw!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"Timestamp must include a timezone at CSV line {line}")
    return stamp


def _finite_nonnegative(raw: str | None, field: str, line: int) -> float:
    try:
        value = float(raw or "")
    except ValueError as exc:
        raise ValueError(f"Invalid {field} at CSV line {line}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be finite and non-negative at CSV line {line}")
    return value


def _metrics(actual: list[float], forecast: list[float]) -> dict[str, float]:
    errors = [predicted - observed for observed, predicted in zip(actual, forecast)]
    return {
        "mae_m3_per_hour": sum(abs(error) for error in errors) / len(errors),
        "rmse_m3_per_hour": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_predicted_minus_actual_m3_per_hour": sum(errors) / len(errors),
        "underforecast_rate": sum(error < 0 for error in errors) / len(errors),
    }


def monitor_forecast_performance(
    input_csv: str | Path,
    output_json: str | Path,
    window_hours: int = 24,
    mae_degradation_fraction: float = 0.25,
) -> dict[str, Any]:
    """Compare the first full evaluation window with the most recent full window."""
    if window_hours < 1:
        raise ValueError("window_hours must be at least 1")
    if not 0.0 <= mae_degradation_fraction <= 5.0:
        raise ValueError("mae_degradation_fraction must be between 0 and 5")

    with Path(input_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    if len(rows) < 2 * window_hours:
        raise ValueError(
            f"Need at least {2 * window_hours} hourly rows for two full monitoring windows"
        )

    timestamps: list[datetime] = []
    actual: list[float] = []
    forecast: list[float] = []
    for line, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp") or "", line)
        if timestamps and (stamp - timestamps[-1]).total_seconds() != 3600:
            raise ValueError(
                f"Expected strictly ordered, continuous hourly records at CSV line {line}"
            )
        timestamps.append(stamp)
        actual.append(_finite_nonnegative(row.get("actual_water_demand_m3"), "actual_water_demand_m3", line))
        forecast.append(_finite_nonnegative(row.get("forecast_water_demand_m3"), "forecast_water_demand_m3", line))

    # Use non-overlapping windows from the start, and always include a final
    # window ending at the newest observation. The final window can overlap the
    # preceding one when the series length is not an exact multiple of the size.
    starts = list(range(0, len(rows) - window_hours + 1, window_hours))
    final_start = len(rows) - window_hours
    if starts[-1] != final_start:
        starts.append(final_start)

    windows: list[dict[str, Any]] = []
    for number, start in enumerate(starts, start=1):
        end = start + window_hours
        windows.append({
            "window": number,
            "start_timestamp": timestamps[start].isoformat(),
            "end_timestamp": timestamps[end - 1].isoformat(),
            "sample_count": window_hours,
            "metrics": _metrics(actual[start:end], forecast[start:end]),
        })

    baseline = windows[0]["metrics"]
    recent = windows[-1]["metrics"]
    baseline_mae = baseline["mae_m3_per_hour"]
    recent_mae = recent["mae_m3_per_hour"]
    relative_change = (
        (recent_mae - baseline_mae) / baseline_mae
        if baseline_mae > 1e-12
        else (0.0 if recent_mae <= 1e-12 else None)
    )
    if baseline_mae <= 1e-12:
        degraded = recent_mae > 1e-12
    else:
        degraded = recent_mae > baseline_mae * (1.0 + mae_degradation_fraction)

    result = {
        "status": "review_recommended" if degraded else "no_mae_degradation_flag",
        "monitor": "water-demand forecast error monitoring",
        "input_csv": str(input_csv),
        "target": "freshwater demand",
        "units": "m3 per hourly interval",
        "row_count": len(rows),
        "window_hours": window_hours,
        "window_count": len(windows),
        "baseline_window": windows[0],
        "most_recent_window": windows[-1],
        "recent_mae_relative_change_vs_baseline": relative_change,
        "mae_degradation_fraction_threshold": mae_degradation_fraction,
        "windows": windows,
        "recommended_action": (
            "Review data quality, operating changes, and model performance; run a fresh chronological backtest before replacing or retraining the model."
            if degraded
            else "Continue monitoring. This result does not prove the model is accurate or that future performance will remain stable."
        ),
        "limitations": [
            "This compares the first full window with the most recent full window; it is a simple alert heuristic, not a formal statistical drift test.",
            "A warning does not automatically retrain or replace a model.",
            "Input forecasts must be genuinely out-of-sample and paired with actual demand at the same timestamps.",
            "Synthetic examples validate software behavior only and do not establish operational forecast quality.",
        ],
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly actual and forecast demand CSV")
    parser.add_argument("--output", default="build/water-demand-forecast/monitor.json")
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--mae-degradation-fraction", type=float, default=0.25)
    args = parser.parse_args()
    try:
        report = monitor_forecast_performance(
            args.input_csv,
            args.output,
            window_hours=args.window_hours,
            mae_degradation_fraction=args.mae_degradation_fraction,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": report["status"],
        "row_count": report["row_count"],
        "baseline_mae_m3_per_hour": report["baseline_window"]["metrics"]["mae_m3_per_hour"],
        "recent_mae_m3_per_hour": report["most_recent_window"]["metrics"]["mae_m3_per_hour"],
        "recommended_action": report["recommended_action"],
        "output": args.output,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
