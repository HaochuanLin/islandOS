from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
from islandos_core.prediction_dispatch_adapter import optimize_prediction_resource_schedule
from islandos_core.prediction_engine import CandidateMetrics, ForecastPoint, PredictionResult


UTC = timezone.utc


def _prediction(signal_id, unit, values, digest_char):
    start = datetime(2026, 11, 1, tzinfo=UTC)
    metrics = CandidateMetrics("seasonal_naive", "1.0", 3, 12, 0.8, 1.1, 5.0)
    points = tuple(
        ForecastPoint(start + timedelta(hours=index + 1), value, value - 0.5, value + 0.5)
        for index, value in enumerate(values)
    )
    return PredictionResult(
        signal_id=signal_id,
        unit=unit,
        model_id="seasonal_naive",
        model_version="1.0",
        input_history_sha256=digest_char * 64,
        confidence_level=0.9,
        interval_method="empirical residual quantile",
        interval_calibration_samples=12,
        backtest=metrics,
        points=points,
        limitations=("statistical baseline",),
    )


def _four_signal_results():
    return {
        "pv_power_kw": _prediction("pv_power_kw", "kW", [5, 6, 4, 3, 2, 1], "a"),
        "wind_power_kw": _prediction("wind_power_kw", "kW", [2, 2, 3, 4, 4, 3], "b"),
        "load_kw": _prediction("load_kw", "kW", [8, 9, 8, 9, 8, 8], "c"),
        "tariff_per_kwh": _prediction(
            "tariff_per_kwh", "USD/kWh", [0.2, -0.05, 0.1, 0.15, 0.08, 0.12], "d"
        ),
    }


def _config():
    return EnergySystemConfig(
        pv_rated_kw=10.0,
        wind_rated_kw=8.0,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=20.0, max_charge_kw=5.0, max_discharge_kw=5.0,
            initial_soc=0.6,
        ),
        diesel=DieselSpec(
            rated_power_kw=10.0, variable_cost_per_kwh=0.3,
            ramp_up_kw_per_hour=10.0,
        ),
    )


def test_generic_prediction_results_run_joint_dispatch_optimizer():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    result = optimize_prediction_resource_schedule(
        _four_signal_results(),
        _config(),
        history_start_utc=start - timedelta(days=7),
        history_end_utc=start,
        grid_available=[True] * 6,
        diesel_available=[True] * 6,
        price_unit="USD/kWh",
        population_size=4,
        generations=1,
        seed=17,
    )
    assert result["scenario_count"] == 4
    assert result["forecast_provenance"]["model_ids"]["pv_power"] == "seasonal_naive"
    assert result["generic_prediction_handoff"]["mode"] == "offline_schedule_search"
    assert result["generic_prediction_handoff"]["device_write_authorized"] is False
    assert len(result["recommendation"]["battery_setpoints_kw"]) == 6


def test_generic_prediction_optimizer_rejects_missing_signal():
    results = _four_signal_results()
    del results["wind_power_kw"]
    start = datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="missing required resource forecasts"):
        optimize_prediction_resource_schedule(
            results,
            _config(),
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
            grid_available=[True] * 6,
            diesel_available=[True] * 6,
            price_unit="USD/kWh",
        )


def test_generic_prediction_optimizer_rejects_unit_guessing():
    results = _four_signal_results()
    results["pv_power_kw"] = _prediction("pv_power_kw", "MW", [0.005] * 6, "a")
    start = datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="must use kW"):
        optimize_prediction_resource_schedule(
            results,
            _config(),
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
            grid_available=[True] * 6,
            diesel_available=[True] * 6,
            price_unit="USD/kWh",
        )


def test_real_prediction_engine_output_runs_joint_resource_optimizer():
    from islandos_core.prediction_engine import (
        ForecastRequest,
        PredictionEngine,
        SignalObservation,
    )

    start = datetime(2026, 11, 1, tzinfo=UTC)
    history_stamps = tuple(start + timedelta(hours=index) for index in range(72))
    raw = {
        "pv_power_kw": ("kW", [max(0.0, 4.0 + 3.0 * ((i % 24) / 24)) for i in range(72)], True),
        "wind_power_kw": ("kW", [3.0 + (i % 5) * 0.2 for i in range(72)], True),
        "load_kw": ("kW", [8.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(72)], True),
        "tariff_per_kwh": ("USD/kWh", [0.08 if i % 24 < 6 else 0.2 for i in range(72)], False),
    }
    engine = PredictionEngine()
    predictions = {}
    targets = tuple(history_stamps[-1] + timedelta(hours=step) for step in range(1, 7))
    for signal_id, (unit, values, non_negative) in raw.items():
        request = ForecastRequest(
            signal_id=signal_id,
            unit=unit,
            history=tuple(
                SignalObservation(timestamp=stamp, value=value)
                for stamp, value in zip(history_stamps, values)
            ),
            target_timestamps=targets,
            non_negative=non_negative,
        )
        predictions[signal_id] = engine.forecast(
            request, backtest_horizon=6, season_length=24
        )

    result = optimize_prediction_resource_schedule(
        predictions,
        _config(),
        history_start_utc=history_stamps[0],
        history_end_utc=history_stamps[-1],
        grid_available=[True] * 6,
        diesel_available=[True] * 6,
        price_unit="USD/kWh",
        population_size=4,
        generations=1,
        seed=23,
    )
    assert result["generic_prediction_handoff"]["device_write_authorized"] is False
    assert set(result["generic_prediction_handoff"]["forecast_model_versions"]) == set(raw)
    assert len(result["recommendation"]["battery_setpoints_kw"]) == 6
