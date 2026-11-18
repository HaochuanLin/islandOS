"""Synthetic demonstration of an auditable, human-reviewed MILP recommendation.

Run from the repository root:
    python examples/operator_decision_record_demo.py

This creates no device command and performs no device write.
"""
from __future__ import annotations

import json

from islandos_core.energy_system import (
    BatterySpec, DieselSpec, EnergySystemConfig, EnergySystemInputs,
)
from islandos_core.operator_decision import (
    build_operator_decision_record, verify_operator_decision_record,
)
from optimization.milp_dispatch_optimizer import optimize_dispatch_milp


def main() -> None:
    config = EnergySystemConfig(
        pv_rated_kw=3.0,
        wind_rated_kw=0.0,
        grid_import_limit_kw=8.0,
        battery=BatterySpec(
            capacity_kwh=4.0,
            max_charge_kw=2.0,
            max_discharge_kw=2.0,
            initial_soc=0.5,
            min_soc=0.1,
            max_soc=0.9,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=5.0,
            variable_cost_per_kwh=0.5,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[1.0, 0.0, 1.0],
        wind_generation_kw=[0.0, 0.0, 0.0],
        load_kw=[2.0, 3.0, 2.0],
        grid_price_per_kwh=[0.1, 0.2, 0.1],
        grid_available=[True, True, True],
        diesel_available=[True, True, True],
    )
    result = optimize_dispatch_milp(inputs, config)
    record = build_operator_decision_record(
        result,
        site_ref="synthetic-demo-site",
        recommendation_id="synthetic-demo-recommendation-001",
        created_at_utc="2026-11-17T00:00:00Z",
        data_provenance="synthetic_demo_data",
        input_refs=["synthetic://islandos/operator-decision-demo/v1"],
        objective_weights={"estimated_operating_cost": 1.0},
        operating_constraints={
            "unmet_load_kwh_max": 0.0,
            "grid_import_limit_kw": 8.0,
            "device_write_authorized": False,
        },
    )
    verification = verify_operator_decision_record(record)
    print(json.dumps({
        "data_provenance": "synthetic_demo_data",
        "decision_record": record,
        "record_verification": verification,
        "device_write_authorized": False,
        "command_generated": False,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
