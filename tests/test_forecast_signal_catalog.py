from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.forecast_signal_catalog import (
    FORECAST_SIGNAL_SPECS,
    forecast_site_signals,
    get_forecast_signal_spec,
)
from islandos_core.prediction_engine import PredictionEngine


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
    assert set(result.results) == set(history)
    assert all(len(item.points) == 6 for item in result.results.values())
    assert result.results["tariff_per_kwh"].unit == "USD/kWh"
    assert all(item.model_id for item in result.results.values())
    assert len(result.input_history_sha256) == 64


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
    assert result.results["tariff_per_kwh"].points[0].predicted_value < 0
    assert result.results["temperature_c"].points[0].predicted_value < 0


def test_registered_candidate_can_replace_builtin_models():
    class FlatCandidate:
        model_id = "customer_flat"
        version = "2.1"

        def predict(self, history, horizon, *, season_length):
            return [float(history[-1])] * horizon

    engine = PredictionEngine(include_builtin_candidates=False)
    engine.register(FlatCandidate())
    result = forecast_site_signals(
        _timestamps(),
        {"process_heat": _series()},
        {"process_heat": "kW_th"},
        3,
        engine=engine,
    )
    assert result.results["process_heat"].model_id == "customer_flat"
    assert result.results["process_heat"].model_version == "2.1"


def test_custom_signal_requires_explicit_unit_but_remains_supported():
    with pytest.raises(ValueError, match="explicit unit"):
        forecast_site_signals(_timestamps(), {"process_heat": _series()}, {"process_heat": ""}, 2)
    result = forecast_site_signals(
        _timestamps(), {"process_heat": _series()}, {"process_heat": "kW_th"}, 2
    )
    assert "process_heat" in result.results


def test_site_forecast_exposes_canonical_planning_contract_to_downstream_services():
    result = forecast_site_signals(
        _timestamps(),
        {"pv_power_kw": _series(offset=10), "load_kw": _series(offset=40)},
        {"pv_power_kw": "kW", "load_kw": "kW"},
        6,
    )
    assert result.planning.timestamps == tuple(
        point.timestamp.astimezone(timezone.utc)
        for point in result.results["pv_power_kw"].points
    )
    assert set(result.planning.values) == {"pv_power_kw", "load_kw"}
    assert result.planning.units["load_kw"] == "kW"
    assert len(result.planning.bundle_sha256) == 64
