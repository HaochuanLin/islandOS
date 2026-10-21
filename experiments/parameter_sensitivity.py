"""One-factor-at-a-time sensitivity analysis for uncertain equipment assumptions.

This experiment reruns the same supplied time series while perturbing one
equipment parameter at a time. It is exploratory sensitivity analysis, not
probabilistic uncertainty quantification and not lifecycle-cost analysis.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import statistics
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_quality import SOURCE_TYPES
from experiments.run_nsga2_from_csv import run_from_csv
from islandos_config import load_config

SENSITIVE_PARAMETERS = (
    ("equipment.ro.specific_energy_kwh_m3", "RO specific energy (kWh/m3)"),
    ("equipment.ice.coefficient_of_performance", "Chiller COP"),
    ("equipment.ro.reservoir_capacity_m3", "Freshwater reservoir capacity (m3)"),
    ("equipment.ice.storage_capacity_kwh_th", "Thermal storage capacity (kWh_th)"),
)
OBJECTIVES = ("water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh")


def _set_path(config: dict, dotted_path: str, value: float) -> None:
    parts = dotted_path.split(".")
    target = config
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _front_summary(result: dict) -> dict:
    front = result["optimization"]["pareto_front"]
    summary = {
        "pareto_candidate_count": len(front),
        "unique_candidates_evaluated": result["optimization"]["unique_candidates_evaluated"],
        "feasible_candidate_count_evaluated": result["optimization"]["feasible_candidate_count_evaluated"],
        "objectives": {},
    }
    for objective in OBJECTIVES:
        values = sorted(float(candidate["objectives"][objective]) for candidate in front)
        summary["objectives"][objective] = (
            {
                "min": values[0],
                "median": statistics.median(values),
                "max": values[-1],
            } if values else None
        )
    return summary


def run_sensitivity(
    input_csv: str | Path,
    output_json: str | Path,
    *,
    config_path: str | Path | None = None,
    source_type: str = "measured",
    relative_change: float = 0.2,
    population_size: int = 20,
    generations: int = 10,
    seed: int = 20261021,
) -> dict:
    if not 0 < relative_change < 1:
        raise ValueError("relative_change must be strictly between 0 and 1")
    base = load_config(config_path)
    # _loaded_from is runtime metadata, not a supported user configuration key.
    base.pop("_loaded_from", None)
    scenarios: list[tuple[str, dict, dict]] = [("baseline", copy.deepcopy(base), {})]

    for dotted_path, label in SENSITIVE_PARAMETERS:
        current = base
        for part in dotted_path.split("."):
            current = current[part]
        value = float(current)
        low = value * (1.0 - relative_change)
        high = value * (1.0 + relative_change)
        # A storage capacity cannot be reduced below its configured initial state.
        if dotted_path == "equipment.ro.reservoir_capacity_m3":
            low = max(low, float(base["equipment"]["ro"]["initial_water_m3"]))
        elif dotted_path == "equipment.ice.storage_capacity_kwh_th":
            low = max(low, float(base["equipment"]["ice"]["initial_storage_kwh_th"]))
        for direction, varied in (("low", low), ("high", high)):
            if abs(varied - value) < 1e-12:
                continue
            config = copy.deepcopy(base)
            _set_path(config, dotted_path, varied)
            # Keep source assumption visible in the generated report.
            config["metadata"]["name"] = f'{base["metadata"].get("name", "IslandOS config")} | {label} {direction}'
            scenarios.append((f"{dotted_path}:{direction}", config, {
                "parameter": dotted_path, "label": label, "direction": direction,
                "baseline_value": value, "tested_value": varied,
                "relative_change_from_baseline": (varied / value - 1.0) if value else None,
            }))

    runs = []
    with tempfile.TemporaryDirectory(prefix="islandos-sensitivity-") as tmp:
        root = Path(tmp)
        for index, (name, config, change) in enumerate(scenarios):
            config_file = root / f"config_{index}.json"
            config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
            run = run_from_csv(
                input_csv, root / f"run_{index}", source_type=source_type,
                population_size=population_size, generations=generations,
                seed=seed, config_path=config_file,
            )
            runs.append({
                "scenario": name,
                "change": change or None,
                "equipment_parameters": run["parameter_configuration"]["equipment"],
                "summary": _front_summary(run),
            })

    report = {
        "project": "IslandOS",
        "method": "one-factor-at-a-time",
        "relative_change_requested": relative_change,
        "seed": seed,
        "population_size": population_size,
        "generations": generations,
        "input_csv": Path(input_csv).name,
        "source_type": source_type,
        "runs": runs,
        "interpretation_limits": [
            "This is a deterministic one-factor-at-a-time stress test, not a probability distribution or confidence interval.",
            "Each run uses the same time series, seed, population size, and generation count.",
            "A changed Pareto front indicates sensitivity to an assumption, not proof that either assumption is more likely.",
            "Costs, discount rates, emissions, equipment failure, forecast uncertainty, and interactions between uncertain parameters are not analyzed.",
            "All conclusions remain conditional on the simplified simulator and supplied input data.",
        ],
    }
    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Hourly input CSV used for every sensitivity case")
    parser.add_argument("--config", help="Optional base JSON configuration")
    parser.add_argument("--source-type", choices=SOURCE_TYPES, default="measured")
    parser.add_argument("--relative-change", type=float, default=0.2, help="Relative perturbation, e.g. 0.2 for +/-20%%")
    parser.add_argument("--population-size", type=int, default=20)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--output", default="build/parameter-sensitivity.json")
    args = parser.parse_args()
    report = run_sensitivity(
        args.input_csv, args.output, config_path=args.config,
        source_type=args.source_type, relative_change=args.relative_change,
        population_size=args.population_size, generations=args.generations,
        seed=args.seed,
    )
    print(json.dumps({
        "output": str(Path(args.output)),
        "scenario_count": len(report["runs"]),
        "baseline": report["runs"][0]["summary"],
        "method": report["method"],
        "limitations": report["interpretation_limits"],
    }, indent=2))


if __name__ == "__main__":
    main()
