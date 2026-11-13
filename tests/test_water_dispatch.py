from islandos_core.water_dispatch import build_price_aware_ro_schedule
from islandos_core.water_resource_adapter import WaterServiceSpec


def test_price_aware_ro_moves_production_into_cheaper_early_hours():
    spec = WaterServiceSpec(
        specific_energy_kwh_per_m3=4.0,
        ro_capacity_m3_per_hour=4.0,
        tank_capacity_m3=8.0,
        initial_inventory_m3=0.0,
        reserve_m3=0.0,
    )
    result = build_price_aware_ro_schedule(
        [1.0, 1.0, 1.0, 1.0],
        [0.05, 0.30, 0.30, 0.30],
        spec=spec,
        lookahead_hours=4,
    )
    assert result["production_m3"][0] == 4.0
    assert result["production_m3"][1] == 0.0
    assert result["production_m3"][2] == 0.0
    assert result["production_m3"][3] == 0.0
    assert result["inventory_end_m3"] == (3.0, 2.0, 1.0, 0.0)
    assert result["device_write_authorized"] is False


def test_price_aware_ro_respects_hourly_capacity_and_tank_bounds():
    spec = WaterServiceSpec(
        specific_energy_kwh_per_m3=2.0,
        ro_capacity_m3_per_hour=1.0,
        tank_capacity_m3=2.0,
        initial_inventory_m3=0.0,
    )
    result = build_price_aware_ro_schedule(
        [0.5, 0.5, 0.5],
        [0.1, 0.2, 0.3],
        spec=spec,
        lookahead_hours=3,
    )
    assert all(0.0 <= value <= 1.0 for value in result["production_m3"])
    assert all(0.0 <= value <= 2.0 for value in result["inventory_end_m3"])
    assert result["total_demand_m3"] == 1.5


def test_price_aware_ro_rejects_misaligned_and_invalid_inputs():
    spec = WaterServiceSpec(4.0, 2.0, 4.0, 1.0)
    import pytest
    with pytest.raises(ValueError, match="equal lengths"):
        build_price_aware_ro_schedule([1.0], [0.1, 0.2], spec=spec)
    with pytest.raises(ValueError, match="finite numeric"):
        build_price_aware_ro_schedule([1.0], [float("nan")], spec=spec)
