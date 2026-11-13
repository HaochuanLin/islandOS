from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.forecast_service import ForecastBundleRequest, ForecastService
from islandos_core.prediction_engine import ForecastRequest, PredictionEngine, SignalObservation


def make_signal(signal_id, unit, values, *, start=None, non_negative=True):
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = tuple(
        SignalObservation(start + timedelta(hours=index), float(value))
        for index, value in enumerate(values)
    )
    targets = tuple(
        start + timedelta(hours=len(values) + index)
        for index in range(6)
    )
    return ForecastRequest(
        signal_id=signal_id, unit=unit, history=history,
        target_timestamps=targets, non_negative=non_negative,
    )


def test_forecast_service_returns_aligned_reproducible_multi_signal_bundle():
    values = [float(index % 24) for index in range(96)]
    request = ForecastBundleRequest((
        make_signal("site_load", "kW", values),
        make_signal("pv_generation", "kW", values),
        make_signal("grid_tariff", "USD/kWh", [0.1 + (index % 24) / 100 for index in range(96)]),
    ))
    service = ForecastService()
    first = service.forecast_bundle(request, initial_history=48, backtest_horizon=24)
    second = service.forecast_bundle(request, initial_history=48, backtest_horizon=24)

    assert set(first.forecasts) == {"site_load", "pv_generation", "grid_tariff"}
    assert first.signal_units["grid_tariff"] == "USD/kWh"
    assert all(len(result.points) == 6 for result in first.forecasts.values())
    assert len(first.bundle_sha256) == 64
    assert first.bundle_sha256 == second.bundle_sha256
    assert "independently" in first.limitations[0]


def test_forecast_bundle_rejects_misaligned_history_or_target_grid():
    values = [float(index % 24) for index in range(72)]
    first = make_signal("load", "kW", values)
    second = make_signal(
        "solar", "kW", values,
        start=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="historical timestamps"):
        ForecastBundleRequest((first, second))

    target_misaligned = ForecastRequest(
        "solar", "kW", second.history,
        tuple(stamp + timedelta(hours=1) for stamp in second.target_timestamps),
    )
    with pytest.raises(ValueError, match="target timestamps"):
        ForecastBundleRequest((first, target_misaligned))


def test_forecast_bundle_rejects_duplicate_signal_ids():
    values = [float(index % 24) for index in range(72)]
    with pytest.raises(ValueError, match="unique"):
        ForecastBundleRequest((
            make_signal("load", "kW", values),
            make_signal("load", "MW", values),
        ))


def test_forecast_bundle_rejects_model_selection_for_unknown_signal():
    values = [float(index % 24) for index in range(72)]
    request = ForecastBundleRequest((make_signal("load", "kW", values),))
    with pytest.raises(ValueError, match="unknown signal IDs"):
        ForecastService().forecast_bundle(
            request, model_ids={"solar": "seasonal_naive"},
            initial_history=48,
        )


class NegativeOutputCandidate:
    model_id = "unsafe_negative"
    version = "1"

    def predict(self, history, horizon, *, season_length):
        return [-1.0] * horizon


def test_forecast_bundle_fails_closed_when_one_signal_cannot_be_forecast():
    values = [float(index % 24) for index in range(72)]
    request = ForecastBundleRequest((
        make_signal("load", "kW", values),
        make_signal("battery_soc", "%", [50.0 + value for value in values]),
    ))
    engine = PredictionEngine()
    engine.register(NegativeOutputCandidate())
    service = ForecastService(engine)
    with pytest.raises(ValueError, match="cannot be negative"):
        service.forecast_bundle(
            request,
            model_ids={"battery_soc": "unsafe_negative"},
            initial_history=48,
        )
