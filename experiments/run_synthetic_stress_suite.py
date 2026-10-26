"""Deterministic stress suite for IslandOS when no site data exists.

Scenarios are synthetic software probes, not statistically representative island
profiles. The suite checks how forecast errors, resource scarcity, demand spikes,
and fail-closed flags propagate through the rolling dispatcher and simulation gate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

from experiments.rolling_horizon_dispatch import generate_synthetic_scenario_csv
from experiments.run_simulated_autonomous_dispatch import run_simulated_autonomous_dispatch


def _scenario_csv(base_csv: str, transform) -> str:
    reader = csv.DictReader(io.StringIO(base_csv))
    rows = list(reader)
    fields = list(reader.fieldnames or [])
    for row in rows:
        transform(row)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _scale(row: dict[str, str], key: str, factor: float) -> None:
    value = float(row[key]) * factor
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid transformed value for {key}")
    row[key] = format(value, ".8g")


def build_stress_cases(hours: int = 48) -> list[dict[str, Any]]:
    """Create a fixed, documented scenario matrix without external datasets."""
    base = generate_synthetic_scenario_csv(hours)
    cases: list[dict[str, Any]] = [{
        "name": "baseline_synthetic",
        "description": "Generated paired actual/forecast baseline; not measured data.",
        "csv": base,
        "gate_flags": {},
    }]
    transforms = [
        ("forecast_overestimate_50pct", "Forecast renewable surplus is 50% higher than the baseline forecast.",
         lambda row: _scale(row, "forecast_surplus_kw", 1.5), {}),
        ("forecast_underestimate_50pct", "Forecast renewable surplus is 50% lower than baseline forecast.",
         lambda row: _scale(row, "forecast_surplus_kw", 0.5), {}),
        ("renewable_drought", "Actual renewable surplus and its forecast are forced to zero for every hour.",
         lambda row: (row.__setitem__("actual_surplus_kw", "0"), row.__setitem__("forecast_surplus_kw", "0")), {}),
        ("water_demand_spike", "Actual and forecast water demand are doubled.",
         lambda row: (_scale(row, "water_demand_m3", 2.0), _scale(row, "forecast_water_demand_m3", 2.0)), {}),
        ("cooling_demand_spike", "Cooling demand is doubled.",
         lambda row: _scale(row, "cooling_demand_kw_th", 2.0), {}),
        ("compound_adverse", "Actual surplus is halved, forecast surplus is 50% optimistic, and both demand profiles rise 50%.",
         lambda row: (_scale(row, "actual_surplus_kw", 0.5), _scale(row, "forecast_surplus_kw", 1.5),
                      _scale(row, "water_demand_m3", 1.5), _scale(row, "forecast_water_demand_m3", 1.5),
                      _scale(row, "cooling_demand_kw_th", 1.5)), {}),
    ]
    for name, description, transform, flags in transforms:
        cases.append({"name": name, "description": description,
                      "csv": _scenario_csv(base, transform), "gate_flags": flags})
    for name, description, flags in (
        ("invalid_telemetry", "Telemetry quality flag is false for every hour.", {"telemetry_valid": False}),
        ("unhealthy_interlocks", "Simulated interlock health flag is false for every hour.", {"interlocks_healthy": False}),
        ("operator_stop", "Operator-stop flag is asserted for every hour.", {"operator_stop": True}),
    ):
        cases.append({"name": name, "description": description, "csv": base, "gate_flags": flags})
    return cases


def run_synthetic_stress_suite(hours: int = 48, max_total_power_kw: float = 500.0) -> dict[str, Any]:
    """Run all deterministic stress cases and return comparable machine-readable evidence."""
    cases = build_stress_cases(hours)
    results = []
    for case in cases:
        report = run_simulated_autonomous_dispatch(
            case["csv"], max_total_power_kw=max_total_power_kw, **case["gate_flags"]
        )
        summary = report["dispatch_summary"]
        results.append({
            "name": case["name"],
            "description": case["description"],
            "dataset_type": report["dataset_type"],
            "input_sha256": report["input_provenance"]["sha256"],
            "hours": report["inputs"]["hours"],
            "gate_action_counts": report["gate_action_counts"],
            "water_unmet_m3": summary["water_unmet_m3"],
            "cooling_unmet_kwh_th": summary["cooling_unmet_kwh_th"],
            "constraint_violation_hours": summary["constraint_violation_hours"],
            "remaining_surplus_kwh": summary["remaining_surplus_kwh"],
            "final_water_inventory_m3": summary["final_water_inventory_m3"],
            "final_cold_inventory_kwh_th": summary["final_cold_inventory_kwh_th"],
            "physical_write_performed": report["physical_write_performed"],
            "live_control_enabled": report["live_control_enabled"],
        })
    expected_names = [case["name"] for case in cases]
    return {
        "report_version": 1,
        "suite": "deterministic_no_site_data_stress_matrix",
        "status": "synthetic_software_stress_not_field_validation",
        "hours_per_case": hours,
        "case_count": len(results),
        "suite_sha256": hashlib.sha256(json.dumps(results, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "all_cases_simulation_only": all(
            not item["physical_write_performed"] and not item["live_control_enabled"] for item in results
        ),
        "expected_case_order": expected_names,
        "results": results,
        "interpretation": [
            "These are designed stress probes, not measured or statistically representative island profiles.",
            "Results demonstrate software behavior under declared assumptions, not forecast accuracy or real-world performance.",
            "Unmet demand is a useful service-risk indicator; zero unmet demand in a synthetic case is not a deployment guarantee.",
            "The suite does not replace site-specific physical constraints, equipment dynamics, or independent safety review.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=48, help="hours per scenario, 1–168")
    parser.add_argument("--max-total-power-kw", type=float, default=500.0,
                        help="illustrative simulation envelope, not a site-approved limit")
    parser.add_argument("--output", type=Path, default=Path("build/synthetic-stress-suite/report.json"))
    args = parser.parse_args(argv)
    report = run_synthetic_stress_suite(args.hours, args.max_total_power_kw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Completed {report['case_count']} synthetic stress cases x {args.hours} hours.")
    print(f"Suite SHA-256: {report['suite_sha256']}")
    print(f"Report: {args.output}")
    print("SYNTHETIC SOFTWARE STRESS ONLY — no physical equipment commands were issued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
