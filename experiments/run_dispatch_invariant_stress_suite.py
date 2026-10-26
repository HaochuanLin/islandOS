"""Seeded property-style stress checks for rolling-dispatch accounting invariants.

Uses synthetic parameter sweeps to detect power-budget, inventory-balance,
capacity-bound, finiteness, and service-accounting regressions. It is not field
validation and does not certify plant safety.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from experiments.compare_dispatch_policies import make_ice, make_ro
from experiments.run_policy_parameter_sweep import POLICIES, build_parameter_sweep_cases
from experiments.rolling_horizon_dispatch import simulate_rolling

TOLERANCE = 2e-5


def run_dispatch_invariant_stress_suite(
    *, hours: int = 24, case_count: int = 12, seed: int = 20261026
) -> dict[str, Any]:
    """Check deterministic dispatch invariants across paired randomized cases."""
    cases = build_parameter_sweep_cases(hours=hours, case_count=case_count, seed=seed)
    ro_config = make_ro().config
    ice_config = make_ice().config
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    policy_runs: dict[str, list[dict[str, Any]]] = {policy: [] for policy in POLICIES}
    checks_per_run = 0

    for case in cases:
        scenario = case["scenario"]
        for policy in POLICIES:
            result = simulate_rolling(
                scenario,
                case["forecast_surplus"],
                policy=policy,
                forecast_water_demand_m3_per_hour=case["forecast_water_demand"],
            )
            run_failures = []
            max_power_excess = 0.0
            max_water_balance_error = 0.0
            max_cold_balance_error = 0.0
            min_water_inventory = math.inf
            max_water_inventory = -math.inf
            min_cold_inventory = math.inf
            max_cold_inventory = -math.inf

            def check(condition: bool, invariant: str, hour_index: int, observed: Any) -> None:
                nonlocal checks_per_run
                checks_per_run += 1
                if not condition:
                    failure = {
                        "case_id": case["case_id"],
                        "policy": policy,
                        "hour_index": hour_index,
                        "invariant": invariant,
                        "observed": observed,
                    }
                    run_failures.append(failure)
                    failures.append(failure)

            for index, row in enumerate(result["hourly_audit"]):
                actual_surplus = float(row["actual_surplus_kw"])
                ro_power = float(row["ro_power_kw"])
                ice_power = float(row["ice_power_kw"])
                power_excess = max(0.0, ro_power + ice_power - actual_surplus)
                max_power_excess = max(max_power_excess, power_excess)
                check(power_excess <= TOLERANCE, "dispatch_power_within_realized_surplus", index, power_excess)

                water_before = float(row["water_inventory_before_m3"])
                water_produced = float(row["water_produced_m3"])
                water_served = float(row["water_served_m3"])
                water_spill = float(row["water_spill_m3"])
                water_after = float(row["water_inventory_m3"])
                water_balance_error = abs(water_before + water_produced - water_served - water_spill - water_after)
                max_water_balance_error = max(max_water_balance_error, water_balance_error)
                check(water_balance_error <= TOLERANCE, "water_inventory_conservation", index, water_balance_error)
                min_water_inventory = min(min_water_inventory, water_after)
                max_water_inventory = max(max_water_inventory, water_after)
                check(
                    ro_config.dead_storage_m3 - TOLERANCE <= water_after <= ro_config.reservoir_capacity_m3 + TOLERANCE,
                    "water_inventory_within_configured_bounds",
                    index,
                    water_after,
                )
                check(
                    -TOLERANCE <= water_served <= scenario.water_demand_m3_per_hour[index] + TOLERANCE,
                    "water_service_within_realized_demand",
                    index,
                    water_served,
                )
                expected_water = ro_power / ro_config.specific_energy_kwh_m3
                check(
                    abs(water_produced - expected_water) <= TOLERANCE,
                    "water_production_matches_power_and_specific_energy",
                    index,
                    abs(water_produced - expected_water),
                )

                cold_before = float(row["cold_inventory_before_kwh_th"])
                cooling_produced = float(row["cooling_produced_kwh_th"])
                cooling_served = float(row["cooling_served_kwh_th"])
                cooling_spill = float(row["cooling_spill_kwh_th"])
                cold_after = float(row["cold_inventory_kwh_th"])
                cold_balance_error = abs(cold_before + cooling_produced - cooling_served - cooling_spill - cold_after)
                max_cold_balance_error = max(max_cold_balance_error, cold_balance_error)
                check(cold_balance_error <= TOLERANCE, "cold_inventory_conservation", index, cold_balance_error)
                min_cold_inventory = min(min_cold_inventory, cold_after)
                max_cold_inventory = max(max_cold_inventory, cold_after)
                check(
                    -TOLERANCE <= cold_after <= ice_config.storage_capacity_kwh_th + TOLERANCE,
                    "cold_inventory_within_configured_bounds",
                    index,
                    cold_after,
                )
                check(
                    -TOLERANCE <= cooling_served <= scenario.cooling_demand_kw_th[index] + TOLERANCE,
                    "cooling_service_within_realized_demand",
                    index,
                    cooling_served,
                )
                expected_cooling = ice_power * ice_config.coefficient_of_performance
                check(
                    abs(cooling_produced - expected_cooling) <= TOLERANCE,
                    "cooling_production_matches_power_and_COP",
                    index,
                    abs(cooling_produced - expected_cooling),
                )
                numeric_values = (
                    actual_surplus, ro_power, ice_power, water_before, water_produced,
                    water_served, water_spill, water_after, cold_before, cooling_produced,
                    cooling_served, cooling_spill, cold_after,
                )
                check(
                    all(math.isfinite(value) for value in numeric_values),
                    "all_audited_numeric_values_are_finite",
                    index,
                    [value for value in numeric_values if not math.isfinite(value)],
                )

            run_row = {
                "case_id": case["case_id"],
                "policy": policy,
                "hours": len(result["hourly_audit"]),
                "invariant_checks": checks_per_run,
                "failed_invariant_count": len(run_failures),
                "max_power_excess_kw": round(max_power_excess, 8),
                "max_water_balance_error_m3": round(max_water_balance_error, 8),
                "max_cold_balance_error_kwh_th": round(max_cold_balance_error, 8),
                "min_water_inventory_m3": round(min_water_inventory, 6),
                "max_water_inventory_m3": round(max_water_inventory, 6),
                "min_cold_inventory_kwh_th": round(min_cold_inventory, 6),
                "max_cold_inventory_kwh_th": round(max_cold_inventory, 6),
                "simulated_constraint_violation_hours": int(result["constraint_violation_hours"]),
            }
            results.append(run_row)
            policy_runs[policy].append(run_row)

    # Report a stable per-run check count rather than the cumulative counter above.
    checks_per_run = len(results[0]["hours"] if results else [])
    checks_per_hour = 9
    total_expected_checks = sum(row["hours"] for row in results) * checks_per_hour
    summary = {}
    for policy, rows in policy_runs.items():
        summary[policy] = {
            "run_count": len(rows),
            "failed_invariant_count": sum(row["failed_invariant_count"] for row in rows),
            "max_power_excess_kw": round(max(row["max_power_excess_kw"] for row in rows), 8),
            "max_water_balance_error_m3": round(max(row["max_water_balance_error_m3"] for row in rows), 8),
            "max_cold_balance_error_kwh_th": round(max(row["max_cold_balance_error_kwh_th"] for row in rows), 8),
            "max_simulated_constraint_violation_hours": max(row["simulated_constraint_violation_hours"] for row in rows),
        }
    report: dict[str, Any] = {
        "report_version": 1,
        "suite": "seeded_dispatch_accounting_invariants",
        "status": "synthetic_software_invariant_test_not_field_validation",
        "seed": seed,
        "hours_per_case": hours,
        "randomized_case_count": case_count,
        "total_case_count": len(cases),
        "policy_names": list(POLICIES),
        "policy_summary": summary,
        "runs": results,
        "total_invariant_checks": total_expected_checks,
        "failed_invariant_count": len(failures),
        "all_invariants_passed": not failures,
        "failures": failures[:100],
        "failure_list_truncated": len(failures) > 100,
        "all_results_simulation_only": True,
        "physical_write_performed": False,
        "live_control_enabled": False,
        "interpretation_limits": [
            "Cases are generated synthetic profiles with seeded scaling factors, not measured site distributions.",
            "Passing accounting invariants verifies only the checked simulator behavior, not full physical fidelity.",
            "Nonzero simulated constraint violations are reported separately and are not hidden by accounting checks.",
            "The score and policy rankings are not part of this suite; this suite checks conservation and bounds only.",
        ],
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24, help="hours per case, 1–168")
    parser.add_argument("--cases", type=int, default=12, help="randomized cases plus baseline, 1–200")
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--output", type=Path, default=Path("build/dispatch-invariant-stress/report.json"))
    args = parser.parse_args(argv)
    try:
        report = run_dispatch_invariant_stress_suite(hours=args.hours, case_count=args.cases, seed=args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Dispatch invariants: {report['total_invariant_checks']} checks, {report['failed_invariant_count']} failures.")
    print(f"Report SHA-256: {report['report_sha256']}")
    print(f"Report: {args.output}")
    print("SYNTHETIC INVARIANT TEST ONLY — no physical equipment commands were issued.")
    return 0 if report["all_invariants_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
