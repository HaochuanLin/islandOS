#!/usr/bin/env python3
"""Run a reproducible forecast -> dispatch -> comparison -> audit demo.

This workflow uses synthetic or user-supplied hourly CSV inputs. The built-in
forecast is a trailing-24-hour mean baseline, not a trained or site-validated AI.
Forecasts are strictly rolling-origin: each row only sees earlier demand values.
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
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_energy_water_strategies import Config, compare_strategies, load_site_steps
from islandos_core.forecasting import (
    ForecastModelRegistry, ForecastRequest, WaterObservation,
)
from tools.generate_synthetic_site_csv import FIELDS, generate_rows


class TrailingDayMean:
    """Simple dependency-free baseline; replace with a compatible plug-in."""

    model_id = "trailing-day-mean"
    version = "1.0.0"

    def predict(self, history: Sequence[WaterObservation], target_timestamps: Sequence[datetime]) -> Sequence[float]:
        if len(history) < 24:
            raise ValueError("TrailingDayMean requires at least 24 hourly observations")
        value = mean(point.demand_m3 for point in history[-24:])
        return [value] * len(target_timestamps)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_timestamp(raw: str, row_number: int, assume_timezone: str | None) -> datetime:
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO-8601 timestamp on CSV row {row_number}: {raw!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        if not assume_timezone:
            raise ValueError(
                f"Timestamp on CSV row {row_number} has no timezone. "
                "Use --assume-timezone only when the source timezone is known."
            )
        if assume_timezone.upper() == "UTC":
            stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            raise ValueError("Only --assume-timezone UTC is supported; normalize other zones before use")
    return stamp


def load_rows(path: Path, assume_timezone: str | None) -> tuple[list[dict[str, str]], list[datetime]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)):
            raise ValueError("Input CSV must have a unique, non-empty header")
        missing = sorted(set(FIELDS) - set(headers))
        if missing:
            raise ValueError("Input CSV missing required columns: " + ", ".join(missing))
        rows = list(reader)
    if len(rows) < 25:
        raise ValueError("At least 25 hourly rows are required for a 24-hour warm-up and one forecast")
    stamps: list[datetime] = []
    for i, row in enumerate(rows, start=2):
        if None in row or any(row.get(name) is None for name in FIELDS):
            raise ValueError(f"Malformed CSV row {i}: fields do not match the header")
        stamp = parse_timestamp(row["timestamp"], i, assume_timezone)
        if stamps and ((stamp.utcoffset() is None) != (stamps[-1].utcoffset() is None)):
            raise ValueError(f"Timezone format changes within input (row {i})")
        if stamps and (stamp - stamps[-1]).total_seconds() != 3600:
            raise ValueError(f"Input timestamps must be continuous hourly values (row {i})")
        stamps.append(stamp)
        for field in ("renewable_surplus_kw", "diesel_displacement_potential_kw",
                      "grid_price_per_kwh", "water_demand_m3", "backup_available_kw"):
            try:
                value = float(row[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be numeric on row {i}") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field} must be finite and non-negative on row {i}")
        for field in ("off_peak", "grid_available"):
            if row[field].strip().lower() not in {"1", "0", "true", "false", "yes", "no", "y", "n"}:
                raise ValueError(f"{field} must be a boolean flag on row {i}")
    return rows, stamps


def load_plugin(spec: str | None):
    if not spec:
        return TrailingDayMean()
    if ":" not in spec:
        raise ValueError("Plugin must use module.path:ClassName syntax")
    module_name, class_name = spec.split(":", 1)
    if not module_name or not class_name:
        raise ValueError("Plugin must use module.path:ClassName syntax")
    module = importlib.import_module(module_name)
    plugin_class = getattr(module, class_name)
    return plugin_class()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="hourly CSV; omit to generate a synthetic dataset")
    parser.add_argument("--output-dir", type=Path, default=Path("build/forecast-dispatch-demo"))
    parser.add_argument("--overwrite", action="store_true", help="allow replacing files in a non-empty output directory")
    parser.add_argument("--hours", type=int, default=168, help="synthetic rows, 25–8784")
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--start", default="2026-01-01T00:00:00")
    parser.add_argument("--assume-timezone", choices=["UTC"], default=None,
                        help="explicitly attach UTC to naive input timestamps; required for naive user CSVs")
    parser.add_argument("--plugin", help="trusted plug-in as module.path:ClassName")
    parser.add_argument("--ro-rated-power-kw", type=float, default=10.0)
    parser.add_argument("--specific-energy-kwh-m3", type=float, default=4.0)
    parser.add_argument("--tank-capacity-m3", type=float, default=50.0)
    parser.add_argument("--initial-water-m3", type=float, default=10.0)
    parser.add_argument("--min-run-hours", type=int, default=1)
    args = parser.parse_args(argv)

    try:
        out = args.output_dir
        if out.exists() and any(out.iterdir()) and not args.overwrite:
            raise ValueError(f"Output directory is not empty: {out}. Choose a new directory or pass --overwrite.")
        if args.input:
            input_path = args.input
            rows, stamps = load_rows(input_path, args.assume_timezone)
            effective_timezone = args.assume_timezone
            input_type = "user_supplied_unverified"
        else:
            if args.hours < 25 or args.hours > 8784:
                raise ValueError("--hours must be between 25 and 8784")
            start = datetime.fromisoformat(args.start)
            if start.tzinfo is not None:
                raise ValueError("--start must be a naive local timestamp; use input timestamps with explicit offsets for site data")
            rows = generate_rows(args.hours, args.seed, start)
            input_path = out / "synthetic_input.csv"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            write_csv(input_path, rows)
            effective_timezone = "UTC"
            rows, stamps = load_rows(input_path, effective_timezone)
            input_type = "synthetic"
        plugin = load_plugin(args.plugin)
        registry = ForecastModelRegistry()
        registry.register(plugin)

        forecast_rows: list[dict] = []
        predicted: list[float] = []
        actual: list[float] = []
        warmup = 24
        for i in range(warmup, len(rows)):
            history = tuple(
                WaterObservation(stamps[j], float(rows[j]["water_demand_m3"]))
                for j in range(i - warmup, i)
            )
            request = ForecastRequest(history=history, target_timestamps=(stamps[i],))
            result = registry.forecast(plugin.model_id, request)
            value = result.points[0].predicted_demand_m3
            predicted.append(value)
            actual.append(float(rows[i]["water_demand_m3"]))
            row = dict(rows[i])
            row["water_demand_m3"] = f"{value:.9f}"
            row["actual_water_demand_m3"] = rows[i]["water_demand_m3"]
            row["predicted_water_demand_m3"] = f"{value:.9f}"
            row["forecast_model_id"] = result.model_id
            row["forecast_model_version"] = result.model_version
            row["input_history_sha256"] = result.input_history_sha256
            forecast_rows.append(row)

        out.mkdir(parents=True, exist_ok=True)
        forecast_csv = out / "forecast_dispatch_input.csv"
        # Keep the strategy engine's stable input contract; the separate forecast
        # audit contains actual values and provenance without leaking future demand.
        engine_rows = [{field: row[field] for field in FIELDS} for row in forecast_rows]
        write_csv(forecast_csv, engine_rows)
        audit_path = out / "forecast_audit.csv"
        write_csv(audit_path, forecast_rows)

        actual_rows_path = out / "actual_demand_reference_input.csv"
        write_csv(actual_rows_path, [{field: row[field] for field in FIELDS} for row in rows[warmup:]])
        forecast_steps = load_site_steps(forecast_csv)
        actual_steps = load_site_steps(actual_rows_path)
        config = Config(
            ro_rated_power_kw=args.ro_rated_power_kw,
            specific_energy_kwh_m3=args.specific_energy_kwh_m3,
            tank_capacity_m3=args.tank_capacity_m3,
            initial_water_m3=args.initial_water_m3,
            min_run_hours=args.min_run_hours,
        )
        forecast_detail, forecast_summary = compare_strategies(forecast_steps, config)
        actual_detail, actual_summary = compare_strategies(actual_steps, config)
        for row in forecast_summary:
            row["demand_basis"] = "rolling_forecast"
        for row in actual_summary:
            row["demand_basis"] = "realized_demand_reference"
        summary_path = out / "strategy_comparison.csv"
        write_csv(summary_path, forecast_summary + actual_summary)
        audit_strategy_path = out / "strategy_timestep_audit.csv"
        for row in forecast_detail:
            row["demand_basis"] = "rolling_forecast"
        for row in actual_detail:
            row["demand_basis"] = "realized_demand_reference"
        write_csv(audit_strategy_path, forecast_detail + actual_detail)

        forecast_mae = mean(abs(p - a) for p, a in zip(predicted, actual))
        forecast_bias = mean(p - a for p, a in zip(predicted, actual))
        artifact_paths = {
            "forecast_dispatch_input": forecast_csv,
            "forecast_audit": audit_path,
            "strategy_comparison": summary_path,
            "strategy_timestep_audit": audit_strategy_path,
            "actual_demand_reference_input": actual_rows_path,
        }
        artifact_manifest = {
            name: {"file": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for name, path in artifact_paths.items()
        }
        report = {
            "report_version": 1,
            "artifacts": artifact_manifest,
            "status": "illustrative_forecast_dispatch_screening_only",
            "dataset_type": input_type,
            "is_measured_site_data": False if input_type == "synthetic" else None,
            "input": {"file": input_path.name, "sha256": sha256_file(input_path), "rows": len(rows)},
            "time_alignment": {
                "timezone_assumption": effective_timezone,
                "warmup_hours_excluded_from_dispatch_comparison": warmup,
                "forecast_rows_compared": len(predicted),
                "first_forecast_timestamp": stamps[warmup].isoformat(),
                "last_forecast_timestamp": stamps[-1].isoformat(),
            },
            "forecast": {
                "model_id": plugin.model_id,
                "model_version": plugin.version,
                "input_history_policy": "immediately preceding 24 realized demand observations only",
                "dispatch_exogenous_inputs_policy": (
                    "Renewable surplus, diesel-displacement potential, grid price, off-peak status, "
                    "grid availability, and backup availability are taken from timestamp-aligned input "
                    "rows; this workflow does not forecast these signals. Strategy results therefore "
                    "must not be interpreted as a fully forecast-driven operational dispatch."
                ),
                "mae_m3_per_hour": forecast_mae,
                "bias_forecast_minus_actual_m3_per_hour": forecast_bias,
                "input_history_hashes_in": audit_path.name,
            },
            "dispatch": {
                "parameters": {
                    "ro_rated_power_kw": config.ro_rated_power_kw,
                    "specific_energy_kwh_m3": config.specific_energy_kwh_m3,
                    "tank_capacity_m3": config.tank_capacity_m3,
                    "initial_water_m3": config.initial_water_m3,
                    "min_run_hours": config.min_run_hours,
                },
                "forecast_strategy_summaries": forecast_summary,
                "realized_demand_reference_summaries": actual_summary,
                "outputs": {
                    "forecast_input_csv": forecast_csv.name,
                    "forecast_audit_csv": audit_path.name,
                    "strategy_comparison_csv": summary_path.name,
                    "strategy_timestep_audit_csv": audit_strategy_path.name,
                },
            },
            "limitations": [
                "The built-in trailing-day mean is a baseline, not a trained AI model.",
                "Only water demand is forecast here; renewable, grid, price, off-peak, and backup signals are timestamp-aligned input values, not forecasts.",
                "Dispatch comparisons are not fully forecast-driven and must not be treated as deployable operational schedules.",
                "Synthetic runs are software fixtures, not measured site evidence.",
                "Realized-demand comparison is an offline reference, not a deployable forecast policy.",
                "This report is not a safety assessment, equipment command, or site performance guarantee.",
                "Only import trusted plug-in code; custom plug-ins execute as Python code.",
            ],
        }
        report_path = out / "run_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
        parser.error(str(exc))
    except Exception as exc:
        # A third-party forecasting plug-in can raise arbitrary exceptions. Keep
        # this CLI fail-closed and user-readable rather than emitting a traceback
        # that looks like a partial successful run.
        parser.error(f"Workflow failed: {type(exc).__name__}: {exc}")

    print(f"Completed forecast -> dispatch workflow: {len(predicted)} forecast rows.")
    print(f"Forecast MAE: {forecast_mae:.6f} m3/hour")
    print(f"Strategy comparison: {summary_path}")
    print(f"Audited report: {report_path}")
    print("ILLUSTRATIVE SCREENING ONLY — not measured site performance or operational advice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
