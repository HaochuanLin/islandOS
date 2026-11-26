"""Tests for canonical-engine evaluation of public OPSD history."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from examples.phase2_opsd_backtest import (
    _canonical_prediction_report,
    _canonicalize_opsd_history,
    _score_holdout,
    build_parser,
)


def _dataset(count=120):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        timestamps=tuple(start + timedelta(hours=index) for index in range(count)),
        history={
            "load": tuple(1.0 + (index % 24) * 0.01 for index in range(count)),
            "solar": tuple(max(0.0, 0.5 + 0.4 * ((index % 24) / 12 - 1)) for index in range(count)),
            "wind": tuple(0.3 + (index % 7) * 0.01 for index in range(count)),
            "price": tuple(-10.0 if index % 24 < 3 else 40.0 for index in range(count)),
        },
        units={"load": "MW", "solar": "MW", "wind": "MW", "price": "EUR/MWh"},
        data_sha256="a" * 64,
    )


def test_opsd_units_are_explicitly_converted_to_canonical_site_units():
    history, units, mapping = _canonicalize_opsd_history(_dataset(count=4))

    assert history["load_kw"] == pytest.approx((1000.0, 1010.0, 1020.0, 1030.0))
    assert history["tariff_per_kwh"] == pytest.approx((-0.01, -0.01, -0.01, 0.04))
    assert units == {
        "load_kw": "kW",
        "pv_power_kw": "kW",
        "wind_power_kw": "kW",
        "tariff_per_kwh": "EUR/kWh",
    }
    assert mapping["load"]["multiplier"] == 1000.0
    assert mapping["price"]["multiplier"] == 0.001


def test_opsd_canonicalization_rejects_unexpected_source_units():
    dataset = _dataset(count=4)
    dataset.units["load"] = "kW"

    with pytest.raises(ValueError, match="source unit mismatch"):
        _canonicalize_opsd_history(dataset)


def test_opsd_canonicalization_rejects_unknown_source_signal():
    dataset = _dataset(count=4)
    dataset.history = {"unmapped_signal": (1.0, 2.0, 3.0, 4.0)}
    dataset.units = {"unmapped_signal": "MW"}

    with pytest.raises(ValueError, match="unsupported OPSD signal"):
        _canonicalize_opsd_history(dataset)


def test_holdout_metrics_handle_zero_denominator_without_inventing_wape():
    metrics = _score_holdout((0.0, 0.0), (1.0, -1.0))

    assert metrics["samples"] == 2
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(1.0)
    assert metrics["bias_predicted_minus_actual"] == pytest.approx(0.0)
    assert metrics["wape_percent"] is None


def test_public_history_is_evaluated_by_the_canonical_prediction_engine():
    report = _canonical_prediction_report(
        _dataset(),
        forecast_horizon=6,
        rolling_horizons=(1, 24),
    )

    assert report["engine"] == "canonical PredictionEngine via forecast_site_signals"
    assert report["source_data_sha256"] == "a" * 64
    assert len(report["canonical_bundle_history_sha256"]) == 64
    assert report["holdout_window"] == {
        "method": "single_final_chronological_holdout",
        "training_samples": 114,
        "training_start_utc": _dataset().timestamps[0].isoformat(),
        "training_end_utc": _dataset().timestamps[113].isoformat(),
        "holdout_samples": 6,
        "holdout_start_utc": _dataset().timestamps[114].isoformat(),
        "holdout_end_utc": _dataset().timestamps[119].isoformat(),
        "excluded_from_candidate_selection": True,
        "excluded_from_rolling_origin_evaluation": True,
        "excluded_from_interval_calibration": True,
    }
    assert set(report["signals"]) == {"load", "solar", "wind", "price"}
    for signal in report["signals"].values():
        assert signal["selected_model"]
        assert len(signal["input_history_sha256"]) == 64
        assert signal["selection_backtest"]["fold_metrics"]
        assert signal["holdout_metrics"]["samples"] == 6
        assert signal["holdout_metrics"]["mae"] >= 0
        assert len(signal["forecast_points"]) == 6

        holdout_comparison = signal["holdout_candidate_evaluations"]
        assert "actual holdout values are used only for scoring" in holdout_comparison["method"]
        candidate_models = {
            item["model_id"]: item for item in holdout_comparison["models"]
        }
        assert set(candidate_models) == {
            "persistence", "seasonal_naive", "recent_mean", "linear_trend",
            "ridge_autoregressive_lag_only",
        }
        selected = candidate_models[signal["selected_model"]]
        assert selected["selected_for_forecast"] is True
        assert selected["metrics"] == signal["holdout_metrics"]
        assert all(
            len(item["forecast_points"]) == 6
            for item in candidate_models.values()
        )
        assert set(signal["rolling_origin_candidate_evaluations"]) == {"1", "24"}
        for horizon_result in signal["rolling_origin_candidate_evaluations"].values():
            assert horizon_result["models"]
            assert horizon_result["best_by_mae"] in {
                item["model_id"] for item in horizon_result["models"]
            }
            evaluated_ids = {item["model_id"] for item in horizon_result["models"]}
            excluded_ids = {
                item["model_id"] for item in horizon_result["excluded_candidates"]
            }
            assert evaluated_ids.isdisjoint(excluded_ids)
            assert evaluated_ids | excluded_ids == {
                "persistence",
                "seasonal_naive",
                "recent_mean",
                "linear_trend",
                "ridge_autoregressive_lag_only",
            }
            assert all(item["reason"] for item in horizon_result["excluded_candidates"])
            for model in horizon_result["models"]:
                assert "bias_predicted_minus_actual" in model
                assert model["fold_metrics"]
                assert all(
                    fold["train_samples"] > 0 and fold["samples"] > 0
                    for fold in model["fold_metrics"]
                )

    timestamps = _dataset().timestamps
    horizon_24 = report["signals"]["load"]["rolling_origin_candidate_evaluations"]["24"]
    window = horizon_24["evaluation_window"]
    assert window["initial_history_start_utc"] == timestamps[0].isoformat()
    assert window["initial_history_end_utc"] == timestamps[47].isoformat()
    assert window["first_validation_start_utc"] == timestamps[48].isoformat()
    assert window["last_scored_validation_end_utc"] == timestamps[95].isoformat()
    assert window["complete_folds"] == 2
    assert window["scored_samples"] == 48
    assert window["excluded_trailing_samples"] == 18
    first_fold = horizon_24["models"][0]["fold_metrics"][0]
    assert first_fold["train_start_utc"] == timestamps[0].isoformat()
    assert first_fold["train_end_utc"] == timestamps[47].isoformat()
    assert first_fold["validation_start_utc"] == timestamps[48].isoformat()
    assert first_fold["validation_end_utc"] == timestamps[71].isoformat()


def test_final_holdout_values_cannot_change_model_selection_or_forecast():
    original = _dataset()
    changed = _dataset()
    changed.history["load"] = (
        changed.history["load"][:-6]
        + tuple(value + 100.0 for value in changed.history["load"][-6:])
    )

    original_report = _canonical_prediction_report(original, 6, rolling_horizons=(1, 24))
    changed_report = _canonical_prediction_report(changed, 6, rolling_horizons=(1, 24))
    original_load = original_report["signals"]["load"]
    changed_load = changed_report["signals"]["load"]

    assert changed_load["selected_model"] == original_load["selected_model"]
    assert changed_load["selection_backtest"] == original_load["selection_backtest"]
    assert (
        changed_load["rolling_origin_candidate_evaluations"]
        == original_load["rolling_origin_candidate_evaluations"]
    )
    assert changed_load["forecast_points"] == original_load["forecast_points"]
    assert changed_load["holdout_metrics"] != original_load["holdout_metrics"]

    original_candidates = {
        item["model_id"]: item
        for item in original_load["holdout_candidate_evaluations"]["models"]
    }
    changed_candidates = {
        item["model_id"]: item
        for item in changed_load["holdout_candidate_evaluations"]["models"]
    }
    assert set(original_candidates) == set(changed_candidates)
    for model_id in original_candidates:
        # Changing only holdout actuals cannot change any candidate forecast.
        assert (
            original_candidates[model_id]["forecast_points"]
            == changed_candidates[model_id]["forecast_points"]
        )
        # The same unchanged forecasts are rescored against the changed actuals.
        assert original_candidates[model_id]["metrics"] != changed_candidates[model_id]["metrics"]


def test_canonical_report_requires_minimum_training_history_before_holdout():
    with pytest.raises(ValueError, match="at least 78 contiguous hourly observations"):
        _canonical_prediction_report(_dataset(count=77), forecast_horizon=6)


def test_canonical_rolling_report_accounts_for_incomplete_trailing_block():
    dataset = _dataset(count=125)
    report = _canonical_prediction_report(
        dataset,
        forecast_horizon=6,
        rolling_horizons=(24,),
    )

    evaluation = report["signals"]["load"]["rolling_origin_candidate_evaluations"]["24"]
    window = evaluation["evaluation_window"]

    assert window == {
        "initial_history_samples": 48,
        "initial_history_start_utc": dataset.timestamps[0].isoformat(),
        "initial_history_end_utc": dataset.timestamps[47].isoformat(),
        "first_validation_start_utc": dataset.timestamps[48].isoformat(),
        "last_scored_validation_end_utc": dataset.timestamps[95].isoformat(),
        "validation_horizon_hours": 24,
        "complete_folds": 2,
        "available_complete_folds": 2,
        "evaluated_folds": 2,
        "skipped_complete_folds": 0,
        "skipped_validation_samples": 0,
        "fold_indices": [1, 2],
        "max_rolling_folds": None,
        "selection_method": "all_complete_folds",
        "scored_samples": 48,
        "excluded_trailing_samples": 23,
    }
    assert all(len(model["fold_metrics"]) == 2 for model in evaluation["models"])
    assert "incomplete trailing observations are excluded" in report["rolling_evaluation_scope"].lower()


def test_canonical_rolling_report_samples_folds_evenly_and_reports_skips():
    dataset = _dataset(count=125)
    report = _canonical_prediction_report(
        dataset,
        forecast_horizon=6,
        rolling_horizons=(1,),
        max_rolling_folds=4,
    )

    evaluation = report["signals"]["load"]["rolling_origin_candidate_evaluations"]["1"]
    window = evaluation["evaluation_window"]

    assert window["available_complete_folds"] == 71
    assert window["evaluated_folds"] == 4
    assert window["skipped_complete_folds"] == 67
    assert window["skipped_validation_samples"] == 67
    assert window["fold_indices"] == [1, 24, 47, 71]
    assert window["first_validation_start_utc"] == dataset.timestamps[48].isoformat()
    assert window["last_scored_validation_end_utc"] == dataset.timestamps[118].isoformat()
    assert window["scored_samples"] == 4
    assert window["excluded_trailing_samples"] == 0
    assert window["selection_method"] == (
        "deterministic_even_spacing_with_first_and_last_fold"
    )
    for model in evaluation["models"]:
        assert [fold["fold_index"] for fold in model["fold_metrics"]] == [1, 24, 47, 71]


def test_canonical_rolling_report_rejects_one_fold_cap_when_sampling_is_required():
    with pytest.raises(ValueError, match="at least 2"):
        _canonical_prediction_report(
            _dataset(count=125),
            forecast_horizon=6,
            rolling_horizons=(1,),
            max_rolling_folds=1,
        )


def test_opsd_cli_exposes_a_bounded_rolling_fold_default_and_override():
    parser = build_parser()
    defaults = parser.parse_args(["--csv", "history.csv"])
    configured = parser.parse_args([
        "--csv", "history.csv",
        "--rolling-validation",
        "--max-rolling-folds", "24",
    ])

    assert defaults.max_rolling_folds == 168
    assert configured.max_rolling_folds == 24

