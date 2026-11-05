"""Export a reproducible common-physics schedule-screening report.

Example:
  python tools/run_schedule_screening_demo.py --hours 168 --seed 20261105
All input time series are synthetic; results are not site performance claims.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_core.microgrid_model import MicrogridConfig
from islandos_core.schedule_evaluator import screen_renewable_surplus_candidates
from run_integrated_microgrid_demo import build_synthetic_inputs


def run_screening(hours: int, seed: int, output_dir: str | Path) -> dict:
    """Run three transparent candidates against one identical synthetic scenario."""
    inputs = build_synthetic_inputs(hours, seed)
    config = MicrogridConfig(
        battery_capacity_kwh=240.0,
        battery_initial_soc_kwh=120.0,
        battery_min_soc_kwh=36.0,
        battery_max_charge_kw=60.0,
        battery_max_discharge_kw=60.0,
        battery_charge_efficiency=0.94,
        battery_discharge_efficiency=0.94,
        grid_import_limit_kw=75.0,
        diesel_capacity_kw=80.0,
        ro_rated_power_kw=35.0,
        ro_specific_energy_kwh_per_m3=4.0,
        water_tank_capacity_m3=260.0,
        water_initial_inventory_m3=110.0,
    )
    ranked = screen_renewable_surplus_candidates(inputs, config)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    summary_path = output / "schedule_screening.csv"
    rows = [item.to_dict() | {"rank": rank} for rank, item in enumerate(ranked, start=1)]
    fields = ["rank", "schedule_id", "feasible", "essential_unserved_kwh",
              "unmet_water_m3", "operating_cost", "emissions_kg",
              "renewable_curtailed_kwh", "water_produced_m3", "ro_electricity_kwh"]
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "schema_version": "1.0",
        "project": "IslandOS",
        "experiment": "common_physics_renewable_surplus_schedule_screening",
        "data_provenance": "synthetic_demo_data_not_measured_site_data",
        "seed": seed,
        "hours": hours,
        "time_step_hours": inputs.dt_hours,
        "candidate_generation": {
            "no_ro": "zero RO power request",
            "conservative_surplus_50pct": "50% of max(PV + wind - essential load, 0), capped at RO rating",
            "renewable_surplus_full": "100% of max(PV + wind - essential load, 0), capped at RO rating",
        },
        "ranking": [
            "feasible candidates first",
            "minimize essential unserved energy",
            "minimize unmet water demand",
            "minimize operating cost",
            "minimize emissions",
            "minimize renewable curtailment",
            "schedule_id as deterministic tie-breaker",
        ],
        "assumptions": {
            "ro_rated_power_kw": config.ro_rated_power_kw,
            "ro_specific_energy_kwh_per_m3": config.ro_specific_energy_kwh_per_m3,
            "water_tank_capacity_m3": config.water_tank_capacity_m3,
            "initial_water_inventory_m3": config.water_initial_inventory_m3,
            "same_scenario_and_physical_model_for_all_candidates": True,
        },
        "candidates": rows,
        "interpretation": (
            "Rule-based candidate screening on synthetic inputs. This is not a forecast, "
            "global optimizer, measured site saving, or field validation."
        ),
        "summary_csv": summary_path.name,
    }
    (output / "schedule_screening.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=168)
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--output-dir", default="build/schedule-screening")
    args = parser.parse_args()
    report = run_screening(args.hours, args.seed, args.output_dir)
    print(json.dumps({
        "data_provenance": report["data_provenance"],
        "hours": report["hours"],
        "ranked_candidates": report["candidates"],
        "output_dir": str(Path(args.output_dir)),
    }, indent=2))


if __name__ == "__main__":
    main()
