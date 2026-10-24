"""Evaluate forecast-driven RO simulation against a perfect-foresight reference."""
from __future__ import annotations
import argparse, csv, hashlib, json, math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
import numpy as np
from island_microgrid_ro_sim import Params, simulate, check_min_run

REQUIRED_COLUMNS = ("timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                    "water_demand_m3", "forecast_water_demand_m3")

def _parse_timestamp(raw: str, line: int) -> datetime:
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp at CSV line {line}: {raw!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"Timestamp must include a timezone at CSV line {line}")
    return stamp.astimezone(timezone.utc)

def _load_input(path: str | Path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)
    if not rows:
        raise ValueError("Input CSV must contain at least one hourly row")
    stamps, values = [], {column: [] for column in REQUIRED_COLUMNS[1:]}
    for line, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp_utc") or "", line)
        if stamps and (stamp - stamps[-1]).total_seconds() != 3600:
            raise ValueError(f"Input must contain strictly ordered, continuous hourly rows at CSV line {line}")
        stamps.append(stamp)
        for column in values:
            try:
                number = float(row.get(column) or "")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid {column} at CSV line {line}") from exc
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{column} must be finite and non-negative at CSV line {line}")
            values[column].append(number)
    return stamps, values

def _scenario_metrics(result: dict[str, Any], params: Params) -> dict[str, Any]:
    segments, valid = check_min_run(result["ro_on"], params.min_run_hours)
    return {
        "ro_run_hours": int(np.sum(result["ro_on"])),
        "water_produced_m3": float(np.sum(result["water_prod"])),
        "unmet_water_demand_m3": float(np.sum(result["deficit"])),
        "water_spill_m3": float(np.sum(result["spill"])),
        "backup_energy_kwh": float(np.sum(result["ro_backup"])),
        "emergency_stop_count": int(np.sum(result["emergency_stop"])),
        "minimum_run_constraint_satisfied": bool(valid),
        "minimum_run_segments_hours": segments,
        "final_reservoir_m3": float(result["V"][-1]),
    }

def evaluate_forecast_driven_ro_sim(input_csv: str | Path, output_csv: str | Path,
                                    report_json: str | Path | None = None,
                                    params: Params | None = None) -> dict[str, Any]:
    """Evaluate forecast-based planning using realized power/water for physical execution."""
    params = params or Params()
    timestamps, series = _load_input(input_csv)
    actual_surplus = np.asarray(series["actual_surplus_kw"], dtype=float)
    forecast_surplus = np.asarray(series["forecast_surplus_kw"], dtype=float)
    actual_demand = np.asarray(series["water_demand_m3"], dtype=float)
    forecast_demand = np.asarray(series["forecast_water_demand_m3"], dtype=float)
    zeros = np.zeros(len(timestamps), dtype=float)
    forecast_result = simulate(
        actual_surplus, zeros, zeros, actual_demand, params,
        forecast_curtailment=forecast_surplus, forecast_water_demand=forecast_demand,
    )
    oracle_result = simulate(actual_surplus, zeros, zeros, actual_demand, params)
    forecast_metrics = _scenario_metrics(forecast_result, params)
    oracle_metrics = _scenario_metrics(oracle_result, params)
    surplus_errors, demand_errors = forecast_surplus - actual_surplus, forecast_demand - actual_demand

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
        "actual_water_demand_m3", "forecast_water_demand_m3",
        "forecast_driven_ro_on", "oracle_ro_on", "forecast_driven_ro_backup_kwh",
        "forecast_driven_water_produced_m3", "forecast_driven_storage_start_m3",
        "forecast_driven_storage_end_m3", "forecast_driven_water_deficit_m3",
        "forecast_driven_water_spill_m3", "forecast_driven_emergency_stop",
        "oracle_water_deficit_m3", "oracle_water_spill_m3",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i, stamp in enumerate(timestamps):
            writer.writerow({
                "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
                "actual_surplus_kw": actual_surplus[i], "forecast_surplus_kw": forecast_surplus[i],
                "actual_water_demand_m3": actual_demand[i], "forecast_water_demand_m3": forecast_demand[i],
                "forecast_driven_ro_on": int(forecast_result["ro_on"][i]),
                "oracle_ro_on": int(oracle_result["ro_on"][i]),
                "forecast_driven_ro_backup_kwh": forecast_result["ro_backup"][i],
                "forecast_driven_water_produced_m3": forecast_result["water_prod"][i],
                "forecast_driven_storage_start_m3": forecast_result["V"][i],
                "forecast_driven_storage_end_m3": forecast_result["V"][i + 1],
                "forecast_driven_water_deficit_m3": forecast_result["deficit"][i],
                "forecast_driven_water_spill_m3": forecast_result["spill"][i],
                "forecast_driven_emergency_stop": int(forecast_result["emergency_stop"][i]),
                "oracle_water_deficit_m3": oracle_result["deficit"][i],
                "oracle_water_spill_m3": oracle_result["spill"][i],
            })
    report = {
        "status": "forecast_driven_ro_simulation_evaluated",
        "input_csv": str(input_csv),
        "input_csv_sha256": hashlib.sha256(Path(input_csv).read_bytes()).hexdigest(),
        "hourly_rows": len(timestamps),
        "first_timestamp_utc": timestamps[0].isoformat().replace("+00:00", "Z"),
        "last_timestamp_utc": timestamps[-1].isoformat().replace("+00:00", "Z"),
        "parameters": asdict(params),
        "forecast_quality": {
            "surplus_mae_kw": mean(abs(float(x)) for x in surplus_errors),
            "water_demand_mae_m3_per_hour": mean(abs(float(x)) for x in demand_errors),
            "surplus_mean_bias_forecast_minus_actual_kw": mean(float(x) for x in surplus_errors),
            "water_demand_mean_bias_forecast_minus_actual_m3_per_hour": mean(float(x) for x in demand_errors),
        },
        "forecast_driven_scenario": forecast_metrics,
        "perfect_foresight_reference": oracle_metrics,
        "difference_forecast_minus_reference": {
            "backup_energy_kwh": forecast_metrics["backup_energy_kwh"] - oracle_metrics["backup_energy_kwh"],
            "unmet_water_demand_m3": forecast_metrics["unmet_water_demand_m3"] - oracle_metrics["unmet_water_demand_m3"],
            "water_spill_m3": forecast_metrics["water_spill_m3"] - oracle_metrics["water_spill_m3"],
            "ro_run_hours": forecast_metrics["ro_run_hours"] - oracle_metrics["ro_run_hours"],
        },
        "hourly_output_csv": str(output),
        "limitations": [
            "The perfect-foresight reference is an optimistic oracle, not an achievable operating policy.",
            "The paired input must represent the same site and timestamps as forecast and measured data.",
            "The model is an hourly RO/reservoir prototype; it does not model membrane flushing, detailed startup dynamics, or validated plant protections.",
            "Forecast errors can increase backup use or cause no-backup emergency stops and minimum-run violations.",
            "No live control, online learning, site transfer, or field safety certification is implied.",
        ],
    }
    report_path = Path(report_json) if report_json else output.with_suffix(".report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report["report_json"] = str(report_path)
    return report

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Paired hourly forecast-dispatch CSV")
    parser.add_argument("--output", default="build/forecast-driven-ro/hourly.csv")
    parser.add_argument("--report", help="JSON report path")
    parser.add_argument("--ro-power-kw", type=float, default=400.0)
    parser.add_argument("--specific-energy-kwh-m3", type=float, default=3.5)
    parser.add_argument("--min-run-hours", type=int, default=2)
    parser.add_argument("--start-ratio", type=float, default=0.8)
    parser.add_argument("--keep-ratio", type=float, default=0.5)
    parser.add_argument("--tank-capacity-m3", type=float, default=3000.0)
    parser.add_argument("--tank-initial-m3", type=float, default=800.0)
    parser.add_argument("--tank-min-m3", type=float, default=200.0)
    parser.add_argument("--tank-area-m2", type=float, default=1000.0)
    parser.add_argument("--no-backup-power", action="store_true")
    args = parser.parse_args()
    try:
        params = Params(
            ro_power_kw=args.ro_power_kw, ro_sec_kwh_m3=args.specific_energy_kwh_m3,
            min_run_hours=args.min_run_hours, start_ratio=args.start_ratio,
            keep_ratio=args.keep_ratio, allow_backup_power=not args.no_backup_power,
            res_capacity_m3=args.tank_capacity_m3, res_init_m3=args.tank_initial_m3,
            res_min_m3=args.tank_min_m3, res_area_m2=args.tank_area_m2,
        )
        report = evaluate_forecast_driven_ro_sim(args.input_csv, args.output, args.report, params)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": report["status"],
        "forecast_driven_scenario": report["forecast_driven_scenario"],
        "perfect_foresight_reference": report["perfect_foresight_reference"],
        "report_json": report["report_json"], "hourly_output_csv": report["hourly_output_csv"],
    }, indent=2))

if __name__ == "__main__":
    main()
