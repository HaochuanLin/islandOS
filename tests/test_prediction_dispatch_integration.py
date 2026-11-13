from datetime import datetime, timedelta, timezone

from islandos_core.prediction_dispatch_adapter import build_resource_coordination_inputs
from islandos_core.prediction_engine import CandidateMetrics, ForecastPoint, PredictionResult


UTC = timezone.utc


def _prediction(signal_id, unit, values, digest_char):
    metrics = CandidateMetrics("seasonal_naive", "1.0", 3, 12, 0.8, 1.1, 5.0)
    start = datetime(2026, 11, 1, tzinfo=UTC)
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


def test_generic_four_signal_forecasts_reach_dispatch_input_contract():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    results = {
        "pv_power_kw": _prediction("pv_power_kw", "kW", [5, 6, 4], "a"),
        "wind_power_kw": _prediction("wind_power_kw", "kW", [2, 2, 3], "b"),
        "load_kw": _prediction("load_kw", "kW", [8, 9, 8], "c"),
        "tariff_per_kwh": _prediction("tariff_per_kwh", "currency/kWh", [0.2, -0.05, 0.1], "d"),
    }
    coordinated = build_resource_coordination_inputs(
        results,
        history_start_utc=start - timedelta(days=7),
        history_end_utc=start,
        grid_available=[True, True, False],
        price_unit="currency/kWh",
    )
    assert coordinated.inputs.pv_generation_kw == [5.0, 6.0, 4.0]
    assert coordinated.inputs.wind_generation_kw == [2.0, 2.0, 3.0]
    assert coordinated.inputs.load_kw == [8.0, 9.0, 8.0]
    assert coordinated.inputs.grid_price_per_kwh == [0.2, -0.05, 0.1]
    assert coordinated.inputs.grid_available == [True, True, False]
    assert len(coordinated.history_sha256) == 64


def test_dispatch_handoff_requires_all_four_resource_signals():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    results = {
        "pv_power_kw": _prediction("pv_power_kw", "kW", [5, 6, 4], "a"),
    }
    try:
        build_resource_coordination_inputs(
            results,
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
            grid_available=[True, True, True],
            price_unit="currency/kWh",
        )
    except ValueError as exc:
        assert "missing required resource forecasts" in str(exc)
    else:
        raise AssertionError("missing resource signals must be rejected")
