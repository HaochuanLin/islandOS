from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.forecast_uncertainty import evaluate_prediction_interval


def test_interval_reports_empirical_coverage_and_width_without_probability_claim():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = evaluate_prediction_interval(
        [1, 2, 3, 6], [0, 1, 2, 3], [2, 3, 3.5, 5],
        nominal_coverage=0.9,
        timestamps=[start + timedelta(hours=i) for i in range(4)],
        minimum_samples=4,
    )
    assert result["empirical_coverage"] == pytest.approx(0.75)
    assert result["mean_interval_width"] == pytest.approx(1.875)
    assert result["calibration_evidence"] == "sufficient_sample_screen"
    assert result["joint_scenario_probabilities_available"] is False
    assert result["calibrated_uncertainty_claim_authorized"] is False


def test_interval_marks_small_sample_as_insufficient():
    result = evaluate_prediction_interval([1], [0], [2], nominal_coverage=0.8)
    assert result["calibration_evidence"] == "insufficient_sample"


@pytest.mark.parametrize(
    "actual,lower,upper",
    [([], [], []), ([1, 2], [0], [2, 3]), ([1], [2], [1])],
)
def test_interval_rejects_empty_misaligned_or_inverted_bounds(actual, lower, upper):
    with pytest.raises(ValueError):
        evaluate_prediction_interval(actual, lower, upper, nominal_coverage=0.9)


def test_interval_rejects_non_hourly_or_naive_timestamps():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="hourly contiguous"):
        evaluate_prediction_interval(
            [1, 2], [0, 0], [2, 2], nominal_coverage=0.9,
            timestamps=[start, start + timedelta(hours=2)],
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_prediction_interval(
            [1], [0], [2], nominal_coverage=0.9,
            timestamps=[datetime(2026, 1, 1)],
        )
