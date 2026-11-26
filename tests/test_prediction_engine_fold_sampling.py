"""Tests for bounded, deterministic rolling-origin fold selection."""

import pytest

from islandos_core.prediction_engine import PredictionEngine, _select_fold_indices


def test_fold_selection_is_even_and_keeps_first_and_last_complete_folds():
    assert _select_fold_indices(66, 4) == (0, 21, 43, 65)


def test_fold_selection_is_exhaustive_when_no_limit_or_limit_is_large():
    assert _select_fold_indices(5, None) == (0, 1, 2, 3, 4)
    assert _select_fold_indices(5, 10) == (0, 1, 2, 3, 4)
    assert _select_fold_indices(0, 3) == ()


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "4"])
def test_fold_selection_rejects_invalid_limits(value):
    with pytest.raises(ValueError, match="max_folds"):
        _select_fold_indices(8, value)


def test_sampling_multiple_folds_requires_two_endpoints():
    with pytest.raises(ValueError, match="at least 2"):
        _select_fold_indices(8, 1)


def test_candidate_comparison_uses_identical_sampled_folds_and_original_indices():
    engine = PredictionEngine()
    history = [float(value) for value in range(20)]

    results = engine.evaluate_candidates(
        history,
        initial_history=4,
        horizon=2,
        max_folds=4,
    )

    assert len(results) == 4
    expected_fold_indices = (1, 3, 5, 8)
    expected_training_samples = (4, 8, 12, 18)
    for result in results:
        assert tuple(fold.fold_index for fold in result.fold_metrics) == expected_fold_indices
        assert tuple(fold.train_samples for fold in result.fold_metrics) == expected_training_samples
        assert result.folds == 4
        assert result.samples == 8


def test_candidate_comparison_remains_exhaustive_by_default():
    engine = PredictionEngine()
    results = engine.evaluate_candidates(
        [float(value) for value in range(20)],
        initial_history=4,
        horizon=2,
    )

    assert results
    assert all(result.folds == 8 for result in results)
    assert all(
        tuple(fold.fold_index for fold in result.fold_metrics) == tuple(range(1, 9))
        for result in results
    )


def test_candidate_comparison_rejects_one_fold_limit_when_sampling_is_needed():
    engine = PredictionEngine()
    with pytest.raises(ValueError, match="at least 2"):
        engine.evaluate_candidates(
            [float(value) for value in range(20)],
            initial_history=4,
            horizon=2,
            max_folds=1,
        )
