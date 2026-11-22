"""Tests for the reproducible diesel-savings scenario sweep."""
from experiments.run_diesel_savings_sweep import (
    POLICY_LABELS,
    SCENARIOS,
    _scenario_site,
    _summarise,
)


def test_sweep_scenarios_are_distinct_and_physically_ordered():
    reference = _scenario_site("A_reference")
    diesel_dependent = _scenario_site("B_diesel_dependent")
    limited_storage = _scenario_site("C_variable_renewables_limited_storage")
    flexible_water = _scenario_site("D_larger_flexible_water_load")

    assert diesel_dependent.mean_essential_load_kw > reference.mean_essential_load_kw
    assert diesel_dependent.pv_rated_kw < reference.pv_rated_kw
    assert limited_storage.battery_capacity_kwh < reference.battery_capacity_kwh
    assert flexible_water.ro_rated_power_kw > reference.ro_rated_power_kw
    assert flexible_water.daily_water_demand_m3 > reference.daily_water_demand_m3
    assert set(SCENARIOS) == {"A_reference", "B_diesel_dependent",
                              "C_variable_renewables_limited_storage",
                              "D_larger_flexible_water_load"}


def test_summary_compares_against_fixed_and_simple_rule_without_hiding_shortages():
    rows = []
    for policy, litres, shortage in (
        ("fixed_timetable", 100.0, 0.0),
        ("surplus_rule", 90.0, 0.0),
        ("joint_milp", 80.0, 2.0),
    ):
        rows.append({
            "strategy": policy,
            "diesel_litres_tank_adjusted": litres,
            "unmet_water_m3": shortage,
            "unmet_electric_kwh": 0.0,
            "optimality_proven": True,
        })
    result = _summarise(rows)
    assert result["joint_milp"]["mean_diesel_saving_vs_fixed_pct"] == 20.0
    assert result["joint_milp"]["mean_diesel_saving_vs_simple_rule_pct"] == pytest.approx(100.0 / 9.0)
    assert result["joint_milp"]["all_water_demand_met"] is False
    assert result["joint_milp"]["all_milp_optimal"] is True
    assert POLICY_LABELS["surplus_rule"] == "Simple renewable-surplus rule"


import pytest
