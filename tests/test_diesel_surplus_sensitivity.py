from dataclasses import replace

from islandos_core.impact_scenario import IslandSiteConfig, generate_synthetic_inputs


def test_sensitivity_cases_keep_common_service_and_equipment_defaults():
    base = IslandSiteConfig()
    wind_case = replace(base, wind_rated_kw=70.0)
    tank_case = replace(base, tank_capacity_m3=120.0)
    assert wind_case.daily_water_demand_m3 == base.daily_water_demand_m3
    assert wind_case.ro_rated_power_kw == base.ro_rated_power_kw
    assert tank_case.pv_rated_kw == base.pv_rated_kw
    assert tank_case.diesel_capacity_kw == base.diesel_capacity_kw


def test_same_seed_is_reproducible_within_a_scenario():
    site = replace(IslandSiteConfig(), wind_rated_kw=70.0)
    first = generate_synthetic_inputs(site, days=2, seed=11)
    second = generate_synthetic_inputs(site, days=2, seed=11)
    assert first.sha256() == second.sha256()
