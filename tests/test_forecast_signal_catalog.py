from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.forecast_signal_catalog import (
    FORECAST_SIGNAL_SPECS,
    forecast_site_signals,
    get_forecast_signal_spec,
)


def _timestamps(count=96):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=index) for index in range(count)]


def _series(count=96, offset=0.0):
    return [offset + 20.0 + (index % 24) * 0.2 for index in range(count)]


def test_catalog_covers_supply_demand_price_and_resource_demand():
    assert FORECAST_SIGNAL_SPECS["pv_power_kw"].domain == "energy_supply"
    assert FORECAST_SIGNAL_SPECS["load_kw"].domain == "energy_demand"
    assert FORECAST_SIGNAL_SPECS["tariff_per_kwh"].domain == "price"
    assert FORECAST_SIGNAL_SPECS["water_demand_m3_per_hour"].domain == "resource_demand"
    assert get_forecast_signal_spec("customer_process_load_kw") is None


def test_site_forecast_uses_one_engine_for_multiple_domains():
    history = {
        "pv_power_kw": _series(offset=10),
        "load_kw": _series(offset=40),
        "tariff_per_kwh": _series(offset=0.1),
        "water_demand_m3_per_hour": _series(offset=2),
    }
    units = {
        "pv_power_kw": "kW",
        "load_kw": "kW",
        "tariff_per_kwh": "USD/kWh",
        "water_demand_m3_per_hour": "m3/h",
    }
    result = forecast_site_signals(_timestamps(), history, units, 6)
    assert set(result.forecasts) == set(history)
    assert all(len(item.points) == 6 for item in result.forecasts.values())
    assert result.forecasts["tariff_per_kwh"].unit == "USD/kWh"


def test_known_signal_rejects_unit_mismatch():
    with pytest.raises(ValueError, match="unit mismatch"):
        forecast_site_signals(
            _timestamps(),
            {"pv_power_kw": _series()},
            {"pv_power_kw": "MW"},
            3,
        )


def test_known_nonnegative_signal_rejects_negative_observations():
    values = _series()
    values[20] = -1.0
    with pytest.raises(ValueError, match="non-negative"):
        forecast_site_signals(
            _timestamps(),
            {"pv_power_kw": values},
            {"pv_power_kw": "kW"},
            3,
        )


def test_negative_tariffs_and_temperatures_are_supported():
    history = {
        "tariff_per_kwh": [-0.05 + (index % 24) * 0.001 for index in range(96)],
        "temperature_c": [-5.0 + (index % 24) * 0.1 for index in range(96)],
    }
    result = forecast_site_signals(
        _timestamps(),
        history,
        {"tariff_per_kwh": "EUR/kWh", "temperature_c": "degC"},
        4,
    )
    assert result.forecasts["tariff_per_kwh"].points[0].predicted < 0
    assert result.forecasts["temperature_c"].points[0].predicted < 0


def test_custom_signal_requires_explicit_unit_but_remains_supported():
    with pytest.raises(ValueError, match="explicit unit"):
        forecast_site_signals(_timestamps(), {"process_heat": _series()}, {"process_heat": ""}, 2)
    result = forecast_site_signals(
        _timestamps(), {"process_heat": _series()}, {"process_heat": "kW_th"}, 2
    )
    assert "process_heat" in result.forecasts
