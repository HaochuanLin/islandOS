"""Run the experimental NSGA-II optimizer on a user-supplied hourly site CSV.

Expected columns are the same as data_quality.py:
timestamp,wind_kw,pv_kw,critical_load_kw,water_demand_m3,cooling_demand_kw_th

Wind/PV/critical load are average power over each hourly interval. Surplus is
max(wind + PV - critical load, 0). The optimizer does not optimize critical-load
shortage or backup generation; by default it refuses inputs with any critical
shortfall. It never fills missing data or silently repairs timestamps.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_quality import SOURCE_TYPES, validate_csv
from islandos_config import economics_completeness, load_config
from experiments.compare_dispatch_policies import Scenario
from optimization.nsga2_dispatch_optimizer import optimize_scenario


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _read_validated_csv(path: Path) -> tuple[list[dict], list[datetime]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    timestamps = []
    for row in rows:
        stamp = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
        timestamps.append(stamp)
    return rows, timestamps


def run_from_csv(
    input_csv: str | Path,
    output_dir: str | Path,
    source_type: str = "measured",
    population_size: int = 40,
    generations: int = 30,
    seed: int = 20261021,
    mutation_rate: float = 0.2,
    allow_critical_shortfall: bool = False,
    config_path: str | Path | None = None,
) -> dict:
    config = load_config(config_path)
    input_path = Path(input_csv)
    output_path = Path(output_dir)
    quality = validate_csv(input_path, source_type=source_type, expected_interval_minutes=60)
    if quality["status"] != "valid":
        raise ValueError("Input data failed quality validation: " + json.dumps(quality["issues"][:10]))
    rows, timestamps = _read_validated_csv(input_path)
    economic_status = economics_completeness(config)
    if economic_status["complete_for_current_declared_fields"]:
        first = timestamps[0]
        last = timestamps[-1]
        expected_hours = 8784 if _is_leap_year(first.year) else 8760
        expected_last = datetime(first.year, 12, 31, 23, 0, tzinfo=first.tzinfo)
        expected_first = datetime(first.year, 1, 1, 0, 0, tzinfo=first.tzinfo)
        if (len(timestamps) != expected_hours or first != expected_first
                or last != expected_last or any(stamp.year != first.year for stamp in timestamps)):
            raise ValueError(
                "Lifecycle-cost objective requires a complete calendar-year CSV: "
                "Jan 1 00:00 through Dec 31 23:00 with every hourly row present."
            )

    wind = np.array([float(row["wind_kw"]) for row in rows], dtype=float)
    pv = np.array([float(row["pv_kw"]) for row in rows], dtype=float)
    critical = np.array([float(row["critical_load_kw"]) for row in rows], dtype=float)
    water = np.array([float(row["water_demand_m3"]) for row in rows], dtype=float)
    cooling = np.array([float(row["cooling_demand_kw_th"]) for row in rows], dtype=float)
    net = wind + pv - critical
    critical_shortfall = np.maximum(0.0, -net)
    surplus = np.maximum(0.0, net)

    shortfall_rows = int(np.count_nonzero(critical_shortfall > 1e-9))
    if shortfall_rows and not allow_critical_shortfall:
        raise ValueError(
            f"Critical electricity demand is unmet in {shortfall_rows} hourly row(s). "
            "This optimizer only allocates surplus to flexible loads and cannot optimize "
            "critical-load reliability. Resolve the input or explicitly pass "
            "--allow-critical-shortfall to run a limited exploratory analysis."
        )

    scenario = Scenario(
        name=input_path.stem,
        available_surplus_kw=tuple(float(v) for v in surplus),
        water_demand_m3_per_hour=tuple(float(v) for v in water),
        cooling_demand_kw_th=tuple(float(v) for v in cooling),
    )
    result = optimize_scenario(
        scenario,
        population_size=population_size,
        generations=generations,
        seed=seed,
        mutation_rate=mutation_rate,
        config=config,
    )
    output_path.mkdir(parents=True, exist_ok=True)
    input_summary = {
        "file": input_path.name,
        "source_type": source_type,
        "quality_status": quality["status"],
        "row_count": len(rows),
        "first_timestamp": timestamps[0].isoformat(),
        "last_timestamp": timestamps[-1].isoformat(),
        "interval_minutes": 60,
        "input_units": {
            "wind_kw": "kW average over each hourly interval",
            "pv_kw": "kW average over each hourly interval",
            "critical_load_kw": "kW average over each hourly interval",
            "water_demand_m3": "m3 per hourly interval",
            "cooling_demand_kw_th": "kW_th average over each hourly interval",
        },
        "total_wind_energy_kwh": float(np.sum(wind)),
        "total_pv_energy_kwh": float(np.sum(pv)),
        "total_critical_energy_kwh": float(np.sum(critical)),
        "total_available_surplus_kwh": float(np.sum(surplus)),
        "critical_shortfall_hours": shortfall_rows,
        "critical_shortfall_energy_kwh": float(np.sum(critical_shortfall)),
        "warning": (
            "Critical load shortfall exists; this limited run does not optimize reliability."
            if shortfall_rows else None
        ),
    }
    report = {
        "project": "islandOS",
        "workflow": "user CSV -> strict validation -> net surplus calculation -> NSGA-II -> Pareto output",
        "input_summary": input_summary,
        "data_quality_report": quality,
        "parameter_configuration": {
            "metadata": config.get("metadata", {}),
            "equipment": config["equipment"],
            "search_space": config["search_space"],
            "economics": config["economics"],
            "economics_completeness": economics_completeness(config),
            "source_policy": config.get("parameter_sources", {}),
            "note": "Configuration values are assumptions unless supported by documented sources. The annualized lifecycle-cost objective is enabled only when all required cost fields and a complete calendar-year input profile are present.",
        },
        "optimization": result,
        "interpretation": {
            "pareto_front": "Trade-off candidates; no single candidate is universally best.",
            "objective_scope": (
                "Minimize unmet water, unmet cooling, and unused available surplus"
                + ("; also minimize annualized lifecycle cost" if result["cost_objective_enabled"] else "")
                + "."
            ),
            "not_optimized": [
                "critical-load reliability or backup generation",
                "battery dispatch, emissions, and lifecycle impacts beyond the explicitly modeled annualized cost",
                "site-specific equipment interlocks or safety constraints",
            ],
            "data_note": "The optimizer uses the supplied time series as its scenario; results are not field validation.",
        },
    }
    json_path = output_path / "nsga2_results.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    pareto_path = output_path / "pareto_front.csv"
    objective_fields = list(result["pareto_front"][0]["objectives"]) if result["pareto_front"] else [
        "water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh"
    ]
    fields = [
        "candidate_index", "priority", "ro_min_run_hours", "ro_start_ratio",
        "ro_rated_power_kw", "ice_rated_power_kw", *objective_fields,
    ]
    with pareto_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, candidate in enumerate(result["pareto_front"], start=1):
            writer.writerow({
                "candidate_index": index,
                **candidate["parameters"],
                **candidate["objectives"],
            })
    report["output_files"] = {
        "json": str(json_path),
        "pareto_csv": str(pareto_path),
    }
    # Include output paths in the JSON itself for self-contained provenance.
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly site CSV matching the documented schema")
    parser.add_argument("--output-dir", default="build/site-optimization")
    parser.add_argument("--source-type", choices=SOURCE_TYPES, default="measured")
    parser.add_argument("--population-size", type=int, default=40)
    parser.add_argument("--generations", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--mutation-rate", type=float, default=0.2)
    parser.add_argument("--config", help="JSON equipment/search/economic parameter configuration")
    parser.add_argument(
        "--allow-critical-shortfall", action="store_true",
        help="Allow exploratory optimization despite critical-load deficits; deficits are reported, not optimized.",
    )
    args = parser.parse_args()
    try:
        report = run_from_csv(
            args.input_csv, args.output_dir, args.source_type,
            args.population_size, args.generations, args.seed,
            args.mutation_rate, args.allow_critical_shortfall, args.config,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "input_summary": report["input_summary"],
        "optimization_summary": {
            key: report["optimization"][key]
            for key in ("unique_candidates_evaluated", "decision_space_size",
                        "feasible_candidate_count_evaluated", "pareto_candidate_count")
        },
        "output_files": report["output_files"],
    }, indent=2))


if __name__ == "__main__":
    main()
