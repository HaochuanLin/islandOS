from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.prediction_dispatch_adapter import build_dispatch_forecast_bundle
from islandos_core.prediction_engine import CandidateMetrics, ForecastPoint, PredictionResult


UTC = timezone.utc


def _result(signal_id, start, digest_char):
    metrics = CandidateMetrics(signal_id + "_model", "1.0", 2, 4, 0.5, 0.7, 4.0, -0.25)
    return PredictionResult(
        signal_id=signal_id,
        unit="kW",
        model_id="seasonal_naive",
        model_version="1.0",
        input_history_sha256=digest_char * 64,
        confidence_level=0.9,
        interval_method="empirical residual quantile",
        interval_calibration_samples=4,
        backtest=metrics,
        points=tuple(
            ForecastPoint(start + timedelta(hours=i), 10.0 + i, 8.0 + i, 12.0 + i)
            for i in range(1, 4)
        ),
        limitations=("test only",),
    )


def test_prediction_results_convert_to_aligned_dispatch_bundle():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    results = {
        "pv_power": _result("pv_power", start, "a"),
        "wind_power": _result("wind_power", start, "b"),
    }
    bundle = build_dispatch_forecast_bundle(
        results, history_start_utc=start - timedelta(days=7),
        history_end_utc=start,
    )
    assert set(bundle.forecasts) == {"pv_power", "wind_power"}
    assert bundle.forecasts["pv_power"].points[0].predicted == 11.0
    assert bundle.forecasts["pv_power"].holdout_metrics.bias_predicted_minus_actual == -0.25
    assert bundle.forecasts["wind_power"].unit == "kW"
    assert len(bundle.input_history_sha256) == 64


def test_dispatch_bundle_rejects_misaligned_resource_horizons():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="identical target timestamps"):
        build_dispatch_forecast_bundle(
            {"pv_power": _result("pv_power", start, "a"),
             "wind_power": _result("wind_power", start + timedelta(minutes=15), "b")},
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
        )


def test_dispatch_bundle_rejects_key_signal_mismatch():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="key does not match"):
        build_dispatch_forecast_bundle(
            {"solar": _result("pv_power", start, "a")},
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
        )

 
def test_dispatch_bundle_normalizes_forecast_points_to_utc():
    offset = timezone(timedelta(hours=5))
    start = datetime(2026, 11, 1, tzinfo=offset)
    bundle = build_dispatch_forecast_bundle(
        {"pv_power": _result("pv_power", start, "a")},
        history_start_utc=start - timedelta(days=7),
        history_end_utc=start,
    )

    point = bundle.forecasts["pv_power"].points[0]
    assert point.timestamp.tzinfo == UTC
    assert point.timestamp == (start + timedelta(hours=1)).astimezone(UTC)


def test_dispatch_bundle_rejects_naive_forecast_timestamp():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    result = _result("pv_power", start, "a")
    points = list(result.points)
    points[0] = replace(points[0], timestamp=datetime(2026, 11, 1, 1))
    malformed = replace(result, points=tuple(points))

    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        build_dispatch_forecast_bundle(
            {"pv_power": malformed},
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
        )


def test_dispatch_bundle_rejects_non_hourly_forecast_timestamps():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    result = _result("pv_power", start, "a")
    points = list(result.points)
    points[1] = replace(points[1], timestamp=points[1].timestamp + timedelta(minutes=15))
    malformed = replace(result, points=tuple(points))

    with pytest.raises(ValueError, match="contiguous hourly"):
        build_dispatch_forecast_bundle(
            {"pv_power": malformed},
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
        )


def test_dispatch_bundle_rejects_bounds_that_do_not_contain_prediction():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    result = _result("pv_power", start, "a")
    points = list(result.points)
    points[0] = replace(points[0], lower_bound=13.0)
    malformed = replace(result, points=tuple(points))

    with pytest.raises(ValueError, match="bounds must contain its prediction"):
        build_dispatch_forecast_bundle(
            {"pv_power": malformed},
            history_start_utc=start - timedelta(days=7),
            history_end_utc=start,
        )
