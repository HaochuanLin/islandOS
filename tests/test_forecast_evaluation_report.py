from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from islandos_core.forecast_evaluation_report import evaluate_realized_forecast


def _points():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        SimpleNamespace(timestamp=start + timedelta(hours=i), predicted_value=10.0 + i,
                        lower_bound=9.0 + i, upper_bound=11.0 + i)
        for i in range(3)
    ]


def test_realized_evaluation_reports_error_bias_and_interval_coverage():
    points = _points()
    start = points[0].timestamp
    actuals = {start + timedelta(hours=i): 9.0 + i for i in range(3)}
    report = evaluate_realized_forecast(
        signal_id="load", unit="kW", forecast_points=points, actuals=actuals
    )
    assert report.samples == 3
    assert report.mae == pytest.approx(1.0)
    assert report.rmse == pytest.approx(1.0)
    assert report.bias_predicted_minus_actual == pytest.approx(1.0)
    assert report.interval_coverage_percent == 100.0


def test_realized_evaluation_rejects_missing_actuals():
    with pytest.raises(ValueError, match="missing"):
        evaluate_realized_forecast(
            signal_id="load", unit="kW", forecast_points=_points(), actuals={}
        )


def test_realized_evaluation_rejects_non_finite_actual():
    points = _points()
    with pytest.raises(ValueError, match="finite"):
        evaluate_realized_forecast(
            signal_id="load", unit="kW", forecast_points=points,
            actuals={point.timestamp: float("nan") for point in points},
        )
