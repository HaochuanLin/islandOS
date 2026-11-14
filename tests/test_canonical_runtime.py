from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.canonical_runtime import CanonicalForecastRuntime, to_planning_forecast
from islandos_core.forecast_service import ForecastBundleRequest
from islandos_core.prediction_engine import ForecastRequest, SignalObservation


def _request(signal_id: str, unit: str, offset: float = 0.0):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = tuple(
        SignalObservation(start + timedelta(hours=i), float(i % 24) + offset)
        for i in range(96)
    )
    targets = tuple(start + timedelta(hours=96 + i) for i in range(6))
    return ForecastRequest(signal_id, unit, history, targets)


def test_canonical_runtime_returns_immutable_aligned_planning_arrays():
    request = ForecastBundleRequest((_request("load", "kW"), _request("solar", "kW", 2.0)))
    result = CanonicalForecastRuntime().prepare(
        request, required_units={"load": "kW", "solar": "kW"},
        initial_history=72, backtest_horizon=12,
    )
    assert len(result.timestamps) == 6
    assert set(result.values) == {"load", "solar"}
    assert result.units["load"] == "kW"
    assert len(result.history_digests["solar"]) == 64
    with pytest.raises(TypeError):
        result.values["load"] = (1.0,)


def test_canonical_runtime_rejects_missing_required_signal_before_forecasting():
    request = ForecastBundleRequest((_request("load", "kW"),))
    with pytest.raises(ValueError, match="missing"):
        CanonicalForecastRuntime().prepare(
            request, required_units={"load": "kW", "solar": "kW"}
        )


def test_canonical_runtime_rejects_unit_mismatch():
    request = ForecastBundleRequest((_request("load", "MW"),))
    with pytest.raises(ValueError, match="units"):
        CanonicalForecastRuntime().prepare(
            request, required_units={"load": "kW"}
        )


def test_canonical_planning_contract_rejects_invalid_digest():
    request = ForecastBundleRequest((_request("load", "kW"),))
    result = CanonicalForecastRuntime()._service.forecast_bundle(
        request, initial_history=72, backtest_horizon=12
    )
    object.__setattr__(result, "bundle_sha256", "not-a-digest")
    with pytest.raises(ValueError, match="SHA-256"):
        to_planning_forecast(result, required_units={"load": "kW"})
