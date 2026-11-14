from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from islandos_core.forecast_benchmark import benchmark_forecast


def _fixture():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = [
        SimpleNamespace(timestamp=start + timedelta(hours=i), predicted_value=10.0 + i,
                        lower_bound=9.0 + i, upper_bound=11.0 + i)
        for i in range(3)
    ]
    actuals = {start + timedelta(hours=i): 9.0 + i for i in range(3)}
    baseline = {start + timedelta(hours=i): 8.0 + i for i in range(3)}
    return points, actuals, baseline


def test_benchmark_reports_lead_time_and_baseline_skill():
    points, actuals, baseline = _fixture()
    report = benchmark_forecast(
        signal_id="load", unit="kW", forecast_points=points,
        actuals=actuals, baseline_predictions=baseline,
    )
    assert report.overall.mae == pytest.approx(1.0)
    assert [item.lead_step for item in report.lead_time] == [1, 2, 3]
    assert report.baseline_mae == pytest.approx(2.0)
    assert report.mae_skill_percent == pytest.approx(50.0)


def test_benchmark_reports_undefined_skill_for_perfect_baseline():
    points, actuals, _ = _fixture()
    perfect = {stamp: value for stamp, value in actuals.items()}
    report = benchmark_forecast(
        signal_id="load", unit="kW", forecast_points=points,
        actuals=actuals, baseline_predictions=perfect,
    )
    assert report.baseline_mae == 0.0
    assert report.mae_skill_percent is None


def test_benchmark_requires_exact_baseline_timestamp_coverage():
    points, actuals, baseline = _fixture()
    baseline.pop(next(iter(baseline)))
    with pytest.raises(ValueError, match="exactly"):
        benchmark_forecast(
            signal_id="load", unit="kW", forecast_points=points,
            actuals=actuals, baseline_predictions=baseline,
        )
