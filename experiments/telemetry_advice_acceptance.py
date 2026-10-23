"""Reproducible synthetic acceptance evidence for telemetry-to-dispatch advice."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_advisor import evaluate_dispatch_rows


SCENARIOS = {
    "normal_day": {
        "description": "Moderate water/cooling demand with a daytime renewable-surplus window.",
        "surplus_scale": 1.0, "water_scale": 1.0, "cooling_scale": 1.0,
    },
    "low_renewables": {
        "description": "Low renewable surplus throughout the 24-hour horizon.",
        "surplus_scale": 0.18, "water_scale": 1.0, "cooling_scale": 1.0,
    },
    "water_stress": {
        "description": "Elevated freshwater demand stresses production and tank inventory.",
        "surplus_scale": 0.75, "water_scale": 1.8, "cooling_scale": 1.0,
    },
    "cooling_stress": {
        "description": "Elevated thermal demand stresses cold-storage service.",
        "surplus_scale": 0.8, "water_scale": 1.0, "cooling_scale": 1.7,
    },
}


def make_scenario_rows(name, hours=24):
    if name not in SCENARIOS:
        raise ValueError("unknown scenario: " + str(name))
    if isinstance(hours, bool) or not isinstance(hours, int) or not 2 <= hours <= 168:
        raise ValueError("hours must be an integer between 2 and 168")
    config = SCENARIOS[name]
    rows = []
    start = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)
    previous_water = 4.0 * config["water_scale"]
    for index in range(hours):
        stamp = start + timedelta(hours=index)
        hour = stamp.hour
        daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12))
        surplus = config["surplus_scale"] * max(0.0, 4.0 + 36.0 * daylight + 3.0 * math.sin(index * 0.53))
        water = config["water_scale"] * (3.5 + 0.8 * (hour in range(6, 10) or hour in range(17, 21)) + 0.35 * math.sin(index * 0.41))
        cooling = config["cooling_scale"] * (5.0 + 3.2 * daylight + 0.5 * math.sin(index * 0.31))
        rows.append({
            "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
            "actual_surplus_kw": round(surplus, 6),
            "forecast_surplus_kw": round(max(0.0, surplus * (0.9 + 0.12 * math.sin(index * 0.17))), 6),
            "water_demand_m3": round(max(0.1, water), 6),
            "cooling_demand_kw_th": round(max(0.1, cooling), 6),
            "forecast_water_demand_m3": round(max(0.1, previous_water), 6),
        })
        previous_water = water
    return rows


def build_acceptance_report(hours=24):
    results = {}
    checks = []
    for name, config in SCENARIOS.items():
        rows = make_scenario_rows(name, hours=hours)
        first = evaluate_dispatch_rows(rows, name=name)
        second = evaluate_dispatch_rows(rows, name=name)
        deterministic = (
            first["policy_comparison"] == second["policy_comparison"]
            and first["recommended_policy_for_operator_review"] == second["recommended_policy_for_operator_review"]
            and first["weight_sensitivity"] == second["weight_sensitivity"]
        )
        checks.append({"scenario": name, "check": "deterministic_repeat", "passed": deterministic})
        policies = first["policy_comparison"]
        shape_ok = len(policies) == 4 and len(first["weight_sensitivity"]) == 4
        checks.append({"scenario": name, "check": "four_policies_and_weight_profiles", "passed": shape_ok})
        values_ok = all(
            math.isfinite(float(row[key])) and float(row[key]) >= 0
            for row in policies
            for key in ("water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh", "constraint_violation_hours")
        )
        checks.append({"scenario": name, "check": "finite_nonnegative_metrics", "passed": values_ok})
        winner = first["recommended_policy_for_operator_review"]
        winner_ok = winner is None or winner in first["eligible_policies"]
        checks.append({"scenario": name, "check": "recommendation_is_eligible", "passed": winner_ok})
        audit_summaries = {}
        audits = first["hourly_audit_by_policy"]
        audit_complete = all(len(audits[policy]) == hours for policy in audits)
        checks.append({"scenario": name, "check": "hourly_audit_complete", "passed": audit_complete})
        water_balance_ok = True
        cooling_balance_ok = True
        inventory_nonnegative = True
        for policy, audit in audits.items():
            audit_summaries[policy] = {
                "hours_audited": len(audit),
                "max_water_balance_residual_m3": 0.0,
                "max_cooling_balance_residual_kwh_th": 0.0,
                "minimum_water_inventory_m3": None,
                "minimum_cold_inventory_kwh_th": None,
            }
            for row in audit:
                water_residual = abs(
                    row["water_inventory_m3"] -
                    (row["water_inventory_before_m3"] + row["water_produced_m3"]
                     - row["water_served_m3"] - row["water_spill_m3"])
                )
                cooling_residual = abs(
                    row["cold_inventory_kwh_th"] -
                    (row["cold_inventory_before_kwh_th"] + row["cooling_produced_kwh_th"]
                     - row["cooling_served_kwh_th"] - row["cooling_spill_kwh_th"])
                )
                audit_summaries[policy]["max_water_balance_residual_m3"] = max(
                    audit_summaries[policy]["max_water_balance_residual_m3"], water_residual
                )
                audit_summaries[policy]["max_cooling_balance_residual_kwh_th"] = max(
                    audit_summaries[policy]["max_cooling_balance_residual_kwh_th"], cooling_residual
                )
                current_water = row["water_inventory_m3"]
                current_cold = row["cold_inventory_kwh_th"]
                prior_water = row["water_inventory_before_m3"]
                prior_cold = row["cold_inventory_before_kwh_th"]
                inventory_nonnegative = inventory_nonnegative and min(
                    current_water, current_cold, prior_water, prior_cold
                ) >= -1e-6
                prior_min_water = audit_summaries[policy]["minimum_water_inventory_m3"]
                prior_min_cold = audit_summaries[policy]["minimum_cold_inventory_kwh_th"]
                audit_summaries[policy]["minimum_water_inventory_m3"] = (
                    current_water if prior_min_water is None else min(prior_min_water, current_water)
                )
                audit_summaries[policy]["minimum_cold_inventory_kwh_th"] = (
                    current_cold if prior_min_cold is None else min(prior_min_cold, current_cold)
                )
                water_balance_ok = water_balance_ok and water_residual <= 5e-5
                cooling_balance_ok = cooling_balance_ok and cooling_residual <= 5e-5
        checks.append({"scenario": name, "check": "water_inventory_conservation", "passed": water_balance_ok})
        checks.append({"scenario": name, "check": "cooling_inventory_conservation", "passed": cooling_balance_ok})
        checks.append({"scenario": name, "check": "nonnegative_inventories", "passed": inventory_nonnegative})
        results[name] = {
            "description": config["description"],
            "input_rows": len(rows),
            "status": first["status"],
            "recommended_policy_for_operator_review": winner,
            "eligible_policies": first["eligible_policies"],
            "policy_comparison": policies,
            "weight_sensitivity": first["weight_sensitivity"],
            "weight_sensitivity_winner_counts": first["weight_sensitivity_winner_counts"],
            "hourly_audit_integrity": audit_summaries,
            "recommendation_reason": first["recommendation_reason"],
        }
    return {
        "schema_version": 1,
        "report_type": "synthetic_telemetry_to_dispatch_acceptance",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_status": "synthetic_only_not_site_data_not_field_validation",
        "hours_per_scenario": hours,
        "scenario_count": len(results),
        "scenarios": results,
        "checks": checks,
        "checks_passed": sum(check["passed"] for check in checks),
        "checks_total": len(checks),
        "all_checks_passed": all(check["passed"] for check in checks),
        "limitations": [
            "Synthetic deterministic scenarios are software regression fixtures, not measured island operations.",
            "The recommendation is conditional on model parameters, input definitions, and declared objective weights.",
            "No device authentication, site calibration, field validation, or physical actuation is performed.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--output", default="build/evidence/islandos-acceptance-report.json")
    args = parser.parse_args(argv)
    try:
        report = build_acceptance_report(hours=args.hours)
    except ValueError as exc:
        parser.error(str(exc))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("Acceptance evidence: %d/%d checks passed." % (report["checks_passed"], report["checks_total"]))
    print("Data status: %s" % report["data_status"])
    print("Report: %s" % output)
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
