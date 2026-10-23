"""Fail-closed wrapper: readiness checks must pass before site CSV optimization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from site_readiness import evaluate_readiness
from experiments.run_nsga2_from_csv import run_from_csv


def run_site_scenario(readiness_json, input_csv, output_dir, source_type="measured",
                      max_telemetry_age_minutes=60, config_path=None,
                      population_size=40, generations=30, seed=20261021):
    """Run offline optimization only if the staff-provided readiness snapshot passes."""
    readiness_path = Path(readiness_json)
    payload = json.loads(readiness_path.read_text(encoding="utf-8"))
    gate = evaluate_readiness(
        payload, mode="dispatch",
        max_telemetry_age_minutes=max_telemetry_age_minutes,
    )
    if not gate["can_start"]:
        details = "; ".join(item["message"] for item in gate["blockers"])
        raise ValueError(f"Site readiness gate BLOCKED optimization: {details}")
    report = run_from_csv(
        input_csv=input_csv,
        output_dir=output_dir,
        source_type=source_type,
        population_size=population_size,
        generations=generations,
        seed=seed,
        config_path=config_path,
    )
    report["site_readiness_gate"] = gate
    report["workflow"] = (
        "staff readiness JSON -> fail-closed readiness gate -> strict hourly CSV validation "
        "-> net surplus calculation -> offline NSGA-II -> Pareto output"
    )
    report_path = Path(output_dir) / "nsga2_results.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("readiness_json", help="Staff-prepared site readiness JSON snapshot")
    parser.add_argument("input_csv", help="Hourly input CSV; must pass data-quality validation")
    parser.add_argument("--output-dir", default="build/site-optimization")
    parser.add_argument("--source-type", choices=("measured", "public", "synthetic", "forecast"), default="measured")
    parser.add_argument("--max-telemetry-age-minutes", type=int, default=60)
    parser.add_argument("--config", help="Equipment/search configuration JSON")
    parser.add_argument("--population-size", type=int, default=40)
    parser.add_argument("--generations", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261021)
    args = parser.parse_args()
    try:
        report = run_site_scenario(
            args.readiness_json, args.input_csv, args.output_dir,
            source_type=args.source_type,
            max_telemetry_age_minutes=args.max_telemetry_age_minutes,
            config_path=args.config,
            population_size=args.population_size,
            generations=args.generations,
            seed=args.seed,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "readiness_status": report["site_readiness_gate"]["status"],
        "quality_status": report["data_quality_report"]["status"],
        "pareto_candidate_count": report["optimization"]["pareto_candidate_count"],
        "output_files": report["output_files"],
    }, indent=2))


if __name__ == "__main__":
    main()
