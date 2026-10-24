"""Evaluate forecast-driven dispatch over multiple chronological windows.

This wrapper splits a paired hourly CSV into non-overlapping windows and calls
the single-window evaluator on each window. Each window's persistence benchmark
uses only the previous observed surplus within that window; the first row is
excluded from that window's aligned comparison. This deliberately sacrifices
one row per window to keep comparisons simple and avoid carrying hidden state
across independent window runs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.evaluate_forecast_dispatch import REQUIRED_COLUMNS, evaluate_forecast_dispatch


def evaluate_windows(input_csv: str | Path, window_hours: int = 168) -> dict:
    """Evaluate contiguous non-overlapping windows and summarize outcomes."""
    if not isinstance(window_hours, int) or isinstance(window_hours, bool) or window_hours < 2:
        raise ValueError("window_hours must be an integer >= 2")
    input_path = Path(input_csv)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        duplicates = sorted({name for name in headers if headers.count(name) > 1})
        if duplicates:
            raise ValueError("Input CSV has duplicate columns: " + ", ".join(duplicates))
        missing = set(REQUIRED_COLUMNS) - set(headers)
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        fieldnames = reader.fieldnames
        rows = list(reader)
    for line, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(f"Input CSV has extra fields at CSV line {line}")
    if not rows:
        raise ValueError("Input CSV must contain at least one hourly row")

    windows = []
    skipped_tail_rows = 0
    for start in range(0, len(rows), window_hours):
        chunk = rows[start:start + window_hours]
        if len(chunk) < 2:
            skipped_tail_rows = len(chunk)
            break
        # The underlying evaluator validates timestamp continuity and every value.
        # Use a temporary sibling CSV to avoid leaving intermediate files behind.
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            chunk_path = Path(temp_dir) / "window.csv"
            with chunk_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(chunk)
            result = evaluate_forecast_dispatch(chunk_path)

        baseline = result["persistence_baseline_comparison"]
        aligned_hours = baseline.get("aligned_hours", 0) if baseline.get("status") == "evaluated" else 0
        windows.append({
            "window_number": len(windows) + 1,
            "input_row_start_1based": start + 1,
            "input_row_end_1based": start + len(chunk),
            "first_timestamp_utc": result["time_basis"]["first_timestamp_utc"],
            "last_timestamp_utc": result["time_basis"]["last_timestamp_utc"],
            "input_rows": len(chunk),
            "aligned_evaluation_hours": aligned_hours,
            "forecast_metrics": result["forecast_metrics"],
            "persistence_baseline_comparison": baseline,
            "dispatch_comparison": result["comparison"],
            "policy_scores": {
                name: values["normalized_score"]
                for name, values in result["policy_comparison"].items()
            },
        })

    evaluated = [w for w in windows if w["aligned_evaluation_hours"] > 0]
    if not evaluated:
        raise ValueError("At least one window with two or more hourly rows is required")

    total_hours = sum(w["aligned_evaluation_hours"] for w in evaluated)
    supplied_mae = sum(
        w["persistence_baseline_comparison"]["forecast_metrics"]["supplied_forecast"]["mae_kw"]
        * w["aligned_evaluation_hours"] for w in evaluated
    ) / total_hours
    persistence_mae = sum(
        w["persistence_baseline_comparison"]["forecast_metrics"]["persistence_baseline"]["mae_kw"]
        * w["aligned_evaluation_hours"] for w in evaluated
    ) / total_hours
    supplied_rmse = math.sqrt(sum(
        w["persistence_baseline_comparison"]["forecast_metrics"]["supplied_forecast"]["rmse_kw"] ** 2
        * w["aligned_evaluation_hours"] for w in evaluated
    ) / total_hours)
    persistence_rmse = math.sqrt(sum(
        w["persistence_baseline_comparison"]["forecast_metrics"]["persistence_baseline"]["rmse_kw"] ** 2
        * w["aligned_evaluation_hours"] for w in evaluated
    ) / total_hours)
    score_differences = [
        w["persistence_baseline_comparison"]["dispatch_comparison"][
            "rolling_score_difference_supplied_minus_persistence"
        ] for w in evaluated
    ]
    return {
        "experiment": "chronological multi-window forecast-to-dispatch evaluation",
        "input_csv": str(input_csv),
        "window_hours": window_hours,
        "window_strategy": "non-overlapping chronological windows; one-row tail is skipped",
        "window_count": len(windows),
        "evaluated_window_count": len(evaluated),
        "total_aligned_evaluation_hours": total_hours,
        "skipped_tail_rows": skipped_tail_rows,
        "aggregate_metrics": {
            "supplied_forecast_mae_kw_weighted": supplied_mae,
            "persistence_mae_kw_weighted": persistence_mae,
            "supplied_forecast_rmse_kw_weighted": supplied_rmse,
            "persistence_rmse_kw_weighted": persistence_rmse,
            "mae_skill_vs_persistence": (
                (persistence_mae - supplied_mae) / persistence_mae
                if persistence_mae > 0 else None
            ),
            "rmse_skill_vs_persistence": (
                (persistence_rmse - supplied_rmse) / persistence_rmse
                if persistence_rmse > 0 else None
            ),
            "mean_rolling_score_difference_supplied_minus_persistence": statistics.fmean(score_differences),
            "windows_where_supplied_forecast_dispatch_scores_lower": sum(d < 0 for d in score_differences),
            "windows_where_persistence_dispatch_scores_lower": sum(d > 0 for d in score_differences),
            "ties": sum(d == 0 for d in score_differences),
        },
        "windows": windows,
        "interpretation_limits": [
            "Windows are independent simulations with the simulator's default initial inventories; storage state is not carried between windows.",
            "The first row of each window is omitted from the persistence-aligned comparison.",
            "Aggregate MAE/RMSE are weighted by aligned hours; the mean dispatch-score difference gives each window equal weight.",
            "The weighted forecast metric summary is not a substitute for inspecting each window and raw service-deficit outcomes.",
            "No claim of real-island performance is made; source provenance must be documented separately.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Paired hourly actual/forecast surplus CSV")
    parser.add_argument("--window-hours", type=int, default=168, help="Rows per non-overlapping window (default: 168)")
    parser.add_argument("--output", default="build/forecast-dispatch-windows.json")
    args = parser.parse_args()
    try:
        result = evaluate_windows(args.input_csv, args.window_hours)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "output": str(output),
        "window_count": result["window_count"],
        "total_aligned_evaluation_hours": result["total_aligned_evaluation_hours"],
        "aggregate_metrics": result["aggregate_metrics"],
    }, indent=2))


if __name__ == "__main__":
    main()
