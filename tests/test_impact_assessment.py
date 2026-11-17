"""Tests for the paired synthetic customer-impact assessment."""
import json

import pytest

from examples.synthetic_customer_impact_demo import build_synthetic_case
from islandos_core.energy_system import (
    BatterySpec,
    EnergySystemConfig,
    EnergySystemInputs,
    compare_energy_policies,
)
from islandos_core.impact_assessment import (
    ImpactAssessmentError,
    _audit_dispatch,
    assess_energy_policy_impact,
    calculate_net_customer_value,
)


def assess():
    inputs, config = build_synthetic_case()
    return assess_energy_policy_impact(
        inputs,
        config,
        currency="USD",
        evaluation_period="24-hour synthetic scenario",
        data_provenance="synthetic_demo_data — not measured site data",
    )


def test_synthetic_case_is_paired_and_explicitly_not_customer_evidence():
    report = assess()
    assert report["same_inputs_and_equipment_configuration"] is True
    assert report["baseline_policy"] == "grid_first"
    assert report["candidate_policy"] == "battery_first"
    assert report["candidate_is_optimizer"] is False
    assert report["evidence_classification"] == "synthetic_model_output"
    assert report["data_provenance"].startswith("synthetic_demo_data")
    assert report["equipment_constraint_audit"]["passed"] is True
    assert report["service_equivalence"]["passed"] is True
    assert report["gross_operating_benefit"]["status"] == "qualified"
    assert report["gross_operating_benefit"]["value"] is not None
    assert report["net_customer_value"] is None
    assert report["commercial_costs"] is None


def test_supported_metrics_include_energy_reliability_flex_and_fuel():
    report = assess()
    for side in ("baseline_metrics", "candidate_metrics"):
        metrics = report[side]
        assert metrics["grid_import_kwh"] >= 0
        assert metrics["diesel_generation_kwh"] >= 0
        assert metrics["diesel_fuel_used_liters"] is not None
        assert metrics["renewable_generation_kwh"] >= 0
        assert metrics["renewable_curtailed_kwh"] >= 0
        assert metrics["critical_service_reliability_fraction"] is not None
        assert metrics["flexible_load_served_kwh"] >= 0
    assert any("water production" in item for item in report["not_evaluated_metrics"])


def test_net_customer_value_subtracts_all_four_cost_categories():
    result = calculate_net_customer_value(
        1_000.0,
        {
            "currency": "USD",
            "evaluation_period": "first operating year",
            "software_cost": 100.0,
            "integration_cost": 200.0,
            "maintenance_cost": 50.0,
            "training_cost": 25.0,
        },
        currency="USD",
        evaluation_period="first operating year",
    )
    assert result["gross_operating_benefit"] == 1_000.0
    assert result["total_commercial_cost"] == 375.0
    assert result["net_customer_value"] == 625.0
    assert result["evidence_classification"] == "customer_cost_inputs_not_independently_verified"


@pytest.mark.parametrize(
    "costs, currency, period, message",
    [
        (
            {"currency": "EUR", "evaluation_period": "24h", "software_cost": 0,
             "integration_cost": 0, "maintenance_cost": 0, "training_cost": 0},
            "USD", "24h", "same currency",
        ),
        (
            {"currency": "USD", "evaluation_period": "annual", "software_cost": 0,
             "integration_cost": 0, "maintenance_cost": 0, "training_cost": 0},
            "USD", "24h", "same evaluation period",
        ),
        (
            {"currency": "USD", "evaluation_period": "24h", "software_cost": -1,
             "integration_cost": 0, "maintenance_cost": 0, "training_cost": 0},
            "USD", "24h", "software_cost must be >= 0",
        ),
    ],
)
def test_net_customer_value_rejects_mismatched_or_invalid_costs(costs, currency, period, message):
    with pytest.raises(ImpactAssessmentError, match=message):
        calculate_net_customer_value(
            10.0, costs, currency=currency, evaluation_period=period
        )


def test_non_equivalent_service_withholds_gross_benefit_and_net_value():
    inputs = EnergySystemInputs(
        pv_generation_kw=[0.0, 0.0],
        wind_generation_kw=[0.0, 0.0],
        load_kw=[10.0, 10.0],
        grid_price_per_kwh=[0.1, 0.1],
        grid_available=[True, False],
        critical_load_kw=[10.0, 10.0],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0.0,
        wind_rated_kw=0.0,
        grid_import_limit_kw=10.0,
        battery=BatterySpec(
            capacity_kwh=10.0,
            max_charge_kw=0.0,
            max_discharge_kw=10.0,
            initial_soc=1.0,
            min_soc=0.0,
            max_soc=1.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
        ),
    )
    report = assess_energy_policy_impact(
        inputs, config, currency="USD", evaluation_period="2-hour test",
        data_provenance="synthetic_test_fixture",
    )
    assert report["service_equivalence"]["passed"] is False
    assert report["gross_operating_benefit"]["value"] is None
    assert report["gross_operating_benefit"]["status"] == "withheld"
    assert report["net_customer_value"] is None


def test_equipment_audit_detects_corrupted_energy_balance():
    inputs, config = build_synthetic_case()
    paired = compare_energy_policies(inputs, config)
    broken = dict(paired["grid_first"])
    broken_rows = [dict(row) for row in broken["rows"]]
    broken_rows[0]["energy_balance_residual_kw"] = 1.0
    broken["rows"] = broken_rows
    result = _audit_dispatch(broken, config, "tampered")
    assert result["passed"] is False
    assert result["violation_count"] >= 1


def test_mismatched_input_series_fail_closed():
    inputs, config = build_synthetic_case()
    invalid = EnergySystemInputs(
        pv_generation_kw=inputs.pv_generation_kw,
        wind_generation_kw=inputs.wind_generation_kw[:-1],
        load_kw=inputs.load_kw,
        grid_price_per_kwh=inputs.grid_price_per_kwh,
        grid_available=inputs.grid_available,
        diesel_available=inputs.diesel_available,
        flexible_load_kw=inputs.flexible_load_kw,
        critical_load_kw=inputs.critical_load_kw,
    )
    with pytest.raises(ValueError, match="equal lengths"):
        assess_energy_policy_impact(
            invalid, config, currency="USD", evaluation_period="24h",
            data_provenance="synthetic_test_fixture",
        )


def test_report_is_json_serializable_without_nan_or_infinity():
    report = assess()
    encoded = json.dumps(report, allow_nan=False)
    assert '"net_customer_value": null' in encoded


def test_equipment_audit_detects_diesel_fuel_inventory_mismatch():
    inputs, config = build_synthetic_case()
    paired = compare_energy_policies(inputs, config)
    broken = dict(paired["battery_first"])
    broken_rows = [dict(row) for row in broken["rows"]]
    broken_rows[0]["diesel_fuel_remaining_liters"] += 1.0
    broken["rows"] = broken_rows
    result = _audit_dispatch(broken, config, "tampered_fuel")
    assert result["passed"] is False
    assert any("fuel inventory balance" in item for item in result["violations"])
