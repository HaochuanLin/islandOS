#!/usr/bin/env python3
"""Run an end-to-end synthetic IslandOS strategy comparison with one command.

Outputs are for software onboarding only. They are not site measurements,
validated forecasts, operational recommendations, or safety approvals.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_energy_water_strategies import Config, compare_strategies, load_site_steps
from tools.generate_synthetic_site_csv import FIELDS, generate_rows
from datetime import datetime


def write_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty report: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("build/synthetic-site-demo"))
    parser.add_argument("--hours", type=int, default=168, help="synthetic hourly rows (1–8784)")
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--start", default="2026-01-01T00:00:00", help="naive local ISO timestamp")
    parser.add_argument("--ro-rated-power-kw", type=float, default=20.0)
    parser.add_argument("--specific-energy-kwh-m3", type=float, default=3.5)
    parser.add_argument("--tank-capacity-m3", type=float, default=30.0)
    parser.add_argument("--initial-water-m3", type=float, default=10.0)
    parser.add_argument("--min-run-hours", type=int, default=1)
    args = parser.parse_args(argv)

    try:
        start = datetime.fromisoformat(args.start)
        rows = generate_rows(args.hours, args.seed, start)
        # Validate physical assumptions through the same core configuration contract.
        config = Config(
            ro_rated_power_kw=args.ro_rated_power_kw,
            specific_energy_kwh_m3=args.specific_energy_kwh_m3,
            tank_capacity_m3=args.tank_capacity_m3,
            initial_water_m3=args.initial_water_m3,
            min_run_hours=args.min_run_hours,
        )
        out = args.output_dir
        out.mkdir(parents=True, exist_ok=True)
        input_csv = out / "synthetic_site_hourly.csv"
        with input_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\\n")
            writer.writeheader()
            writer.writerows(rows)
        digest = sha256_file(input_csv)
        manifest_path = out / "synthetic_site_hourly.manifest.json"
        manifest = {
            "manifest_version": 1,
            "dataset_type": "synthetic",
            "is_measured_site_data": False,
            "intended_use": "software onboarding, examples, and tests only",
            "prohibited_use": "operational decisions or claims of real-site performance",
            "file": input_csv.name,
            "sha256": digest,
            "row_count": len(rows),
            "columns": FIELDS,
            "generation": {
                "generator": "tools/run_synthetic_site_demo.py",
                "seed": args.seed,
                "start_local_naive": start.isoformat(timespec="seconds"),
                "hours": len(rows),
                "time_step": "1 hour",
            },
            "time_range": {
                "first_timestamp": rows[0]["timestamp"],
                "last_timestamp": rows[-1]["timestamp"],
                "timezone": "not encoded; timestamps are naive local time",
            },
            "limitations": [
                "Synthetic values are illustrative and not calibrated to a real site.",
                "A matching SHA-256 proves file identity, not measurement authenticity or physical accuracy.",
                "Document the intended site timezone before aligning with external data.",
            ],
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\\n",
            encoding="utf-8",
        )

        steps = load_site_steps(input_csv)
        detail, summary = compare_strategies(steps, config)
        summary_path = out / "strategy_summary.csv"
        audit_path = out / "timestep_audit.csv"
        write_rows(summary_path, summary)
        write_rows(audit_path, detail)
        report = {
            "report_version": 1,
            "dataset_type": "synthetic",
            "is_measured_site_data": False,
            "status": "illustrative_screening_only",
            "input": {
                "path": input_csv.name,
                "sha256": sha256_file(input_csv),
                "manifest": manifest_path.name,
                "rows": len(steps),
            },
            "assumptions": {
                "ro_rated_power_kw": config.ro_rated_power_kw,
                "specific_energy_kwh_m3": config.specific_energy_kwh_m3,
                "tank_capacity_m3": config.tank_capacity_m3,
                "initial_water_m3": config.initial_water_m3,
                "min_run_hours": config.min_run_hours,
            },
            "outputs": {
                "summary_csv": summary_path.name,
                "timestep_audit_csv": audit_path.name,
            },
            "strategy_summary": summary,
            "limitations": [
                "Synthetic inputs are illustrative and are not calibrated to a real island.",
                "Results are conditional on this simplified model and the supplied assumptions.",
                "This command does not produce control commands or safety approval.",
            ],
        }
        report_path = out / "run_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Completed synthetic comparison for {len(steps)} hourly rows.")
    print(f"Input SHA-256: {digest}")
    print(f"Strategy summary: {summary_path}")
    print(f"Hourly audit: {audit_path}")
    print(f"Machine-readable report: {report_path}")
    print("SYNTHETIC SCREENING ONLY — not measured site performance or operational advice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
