"""End-to-end synthetic rolling-dispatch plus fail-closed gate demonstration.

This workflow connects scenario parsing, receding-horizon dispatch, hourly audit
rows, and the independent simulation-only ON/OFF/HOLD gate. It never controls
physical equipment and its default data are synthetic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.rolling_horizon_dispatch import (
    generate_synthetic_scenario_csv,
    parse_scenario_csv,
    simulate_rolling,
)
from experiments.simulated_autonomous_flex_load_gate import evaluate_simulated_action


def run_simulated_autonomous_dispatch(
    scenario_csv: str | None = None,
    *,
    hours: int = 24,
    max_total_power_kw: float = 500.0,
    telemetry_valid: bool = True,
    interlocks_healthy: bool = True,
    operator_stop: bool = False,
    objective_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run one deterministic simulation and gate every hourly dispatch audit row.

    ``scenario_csv=None`` selects a generated synthetic fixture. Explicit CSV is
    treated as user-supplied, unverified input; neither path is site validation.
    Gate flags are caller-supplied simulation fixtures, not live interlock reads.
    """
    if scenario_csv is None:
        csv_text = generate_synthetic_scenario_csv(hours)
        dataset_type = "synthetic"
        scenario_name = "generated_synthetic_fixture"
    else:
        csv_text = scenario_csv
        dataset_type = "user_supplied_unverified"
        scenario_name = "user_supplied_csv"

    parsed = parse_scenario_csv(csv_text, name=scenario_name)
    dispatch = simulate_rolling(
        parsed["scenario"],
        parsed["forecast_surplus_kw"],
        policy="rolling",
        forecast_water_demand_m3_per_hour=parsed["forecast_water_demand_m3_per_hour"],
        forecast_cooling_demand_kw_th=parsed["forecast_cooling_demand_kw_th"],
        objective_weights=objective_weights,
    )

    gated_rows = []
    for row in dispatch["hourly_audit"]:
        decision = evaluate_simulated_action(
            row,
            telemetry_valid=telemetry_valid,
            interlocks_healthy=interlocks_healthy,
            operator_stop=operator_stop,
            max_total_power_kw=max_total_power_kw,
        )
        gated_rows.append({
            "hour_index": row["hour_index"],
            "dispatch": row,
            "gate": decision,
        })

    action_counts = {action: sum(item["gate"]["action"] == action for item in gated_rows)
                     for action in ("ON", "OFF", "HOLD")}
    return {
        "report_version": 1,
        "workflow": "rolling_dispatch_to_simulated_autonomous_gate",
        "status": "simulation_only_not_site_validated",
        "dataset_type": dataset_type,
        "is_measured_site_data": False if dataset_type == "synthetic" else None,
        "mode": "simulation_only",
        "physical_write_performed": False,
        "live_control_enabled": False,
        "requires_site_validation_before_deployment": True,
        "input_provenance": {
            "sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
            "rows": len(parsed["timestamps_utc"]),
            "first_timestamp_utc": parsed["timestamps_utc"][0],
            "last_timestamp_utc": parsed["timestamps_utc"][-1],
            "integrity_note": "SHA-256 identifies these input bytes; it does not authenticate measurement origin or accuracy.",
        },
        "inputs": {
            "hours": len(dispatch["hourly_audit"]),
            "forecast_source": "CSV forecast_surplus_kw and optional forecast_water_demand_m3 / forecast_cooling_demand_kw_th",
            "telemetry_valid_fixture": telemetry_valid,
            "interlocks_healthy_fixture": interlocks_healthy,
            "operator_stop_fixture": operator_stop,
            "max_total_power_kw_illustrative": max_total_power_kw,
            "objective_weights": dispatch["objective_weights"],
        },
        "dispatch_summary": {
            key: dispatch[key] for key in (
                "policy", "objective_weights", "water_unmet_m3", "cooling_unmet_kwh_th",
                "renewable_flexible_load_kwh", "remaining_surplus_kwh",
                "constraint_violation_hours", "final_water_inventory_m3",
                "final_cold_inventory_kwh_th",
            )
        },
        "gate_action_counts": action_counts,
        "hourly_results": gated_rows,
        "limitations": [
            "The default scenario is generated synthetic data, not measured site telemetry.",
            "The dispatch model is simplified and does not represent all plant interlocks, equipment dynamics, or site constraints.",
            "Gate flags are supplied simulation inputs; no sensor authenticity or physical interlock is verified.",
            "ON/OFF/HOLD are simulated RO plan recommendations only; no actuator command is issued.",
            "The power envelope is an illustrative software parameter, not an approved engineering limit.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, help="hourly scenario CSV; omit for synthetic fixture")
    parser.add_argument("--hours", type=int, default=24, help="synthetic fixture length, 1–168 hours")
    parser.add_argument("--max-total-power-kw", type=float, default=500.0,
                        help="illustrative gate envelope; not a site-approved limit")
    parser.add_argument("--telemetry-invalid", action="store_true", help="exercise the fail-closed telemetry gate")
    parser.add_argument("--interlocks-unhealthy", action="store_true", help="exercise the fail-closed interlock gate")
    parser.add_argument("--operator-stop", action="store_true", help="exercise the operator-stop gate")
    parser.add_argument("--water-weight", type=float, default=0.45, help="normalized dispatch objective weight; all three weights must sum to 1")
    parser.add_argument("--cooling-weight", type=float, default=0.45, help="normalized dispatch objective weight; all three weights must sum to 1")
    parser.add_argument("--surplus-weight", type=float, default=0.10, help="normalized dispatch objective weight; all three weights must sum to 1")
    parser.add_argument("--output", type=Path, default=Path("build/simulated-autonomous-dispatch/report.json"))
    args = parser.parse_args(argv)
    try:
        csv_text = args.input_csv.read_text(encoding="utf-8") if args.input_csv else None
        report = run_simulated_autonomous_dispatch(
            csv_text,
            hours=args.hours,
            max_total_power_kw=args.max_total_power_kw,
            telemetry_valid=not args.telemetry_invalid,
            interlocks_healthy=not args.interlocks_unhealthy,
            operator_stop=args.operator_stop,
            objective_weights={
                "water": args.water_weight,
                "cooling": args.cooling_weight,
                "surplus": args.surplus_weight,
            },
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Completed simulation-only dispatch gate for {report['inputs']['hours']} hours.")
    print(f"Gate action counts: {json.dumps(report['gate_action_counts'], sort_keys=True)}")
    print(f"Audited report: {args.output}")
    print("SIMULATION ONLY — no physical equipment commands were issued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
