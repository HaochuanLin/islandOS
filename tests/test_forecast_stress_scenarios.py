import pytest

from islandos_core.forecast_stress_scenarios import build_interval_stress_scenarios


def _intervals():
    return {
        "pv_generation_kw": {"central": [5, 6], "lower": [2, 3], "upper": [7, 8]},
        "load_kw": {"central": [4, 5], "lower": [3, 4], "upper": [6, 7]},
        "grid_price_per_kwh": {"central": [0.1, 0.2], "lower": [0.05, 0.1], "upper": [0.3, 0.4]},
        "water_demand_m3_per_hour": {"central": [1, 1], "lower": [0.8, 0.8], "upper": [1.2, 1.3]},
    }


def test_builds_directional_scenarios_without_assigning_probabilities():
    result = build_interval_stress_scenarios(
        _intervals(), renewable_signals=("pv_generation_kw",),
        demand_signals=("load_kw", "water_demand_m3_per_hour"),
        cost_signals=("grid_price_per_kwh",),
    )
    scenarios = result["scenarios"]
    assert scenarios["central"]["pv_generation_kw"] == [5.0, 6.0]
    assert scenarios["renewable_low_demand_high"]["pv_generation_kw"] == [2.0, 3.0]
    assert scenarios["renewable_low_demand_high"]["load_kw"] == [6.0, 7.0]
    assert scenarios["cost_high"]["grid_price_per_kwh"] == [0.3, 0.4]
    assert scenarios["combined_stress"]["water_demand_m3_per_hour"] == [1.2, 1.3]
    assert result["scenario_probabilities"] is None
    assert "not_define_joint_probabilities" in result["probability_status"]


def test_rejects_misaligned_horizons_and_invalid_interval_order():
    intervals = _intervals()
    intervals["load_kw"]["upper"] = [6]
    with pytest.raises(ValueError, match="share the same horizon"):
        build_interval_stress_scenarios(
            intervals, renewable_signals=("pv_generation_kw",),
            demand_signals=("load_kw", "water_demand_m3_per_hour"),
            cost_signals=("grid_price_per_kwh",),
        )
    intervals = _intervals()
    intervals["pv_generation_kw"]["lower"] = [6, 7]
    with pytest.raises(ValueError, match="lower <= central <= upper"):
        build_interval_stress_scenarios(
            intervals, renewable_signals=("pv_generation_kw",),
            demand_signals=("load_kw", "water_demand_m3_per_hour"),
            cost_signals=("grid_price_per_kwh",),
        )


def test_rejects_role_overlap_and_missing_role_signals():
    with pytest.raises(ValueError, match="more than one"):
        build_interval_stress_scenarios(
            _intervals(), renewable_signals=("pv_generation_kw",),
            demand_signals=("pv_generation_kw",),
            cost_signals=("grid_price_per_kwh",),
        )
    with pytest.raises(ValueError, match="missing forecast intervals"):
        build_interval_stress_scenarios(
            _intervals(), renewable_signals=("wind_generation_kw",),
            demand_signals=("load_kw",), cost_signals=("grid_price_per_kwh",),
        )
