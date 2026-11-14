"""Tests for canonical-engine evaluation of public OPSD history."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from examples.phase2_opsd_backtest import (
    _canonical_prediction_report,
    _canonicalize_opsd_history,
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
    assert history["tariff_per_kwh"] == pytest.approx((-0.01, 0.04, 0.04, 0.04))
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


def test_public_history_is_evaluated_by_the_canonical_prediction_engine():
    report = _canonical_prediction_report(
        _dataset(),
        forecast_horizon=6,
        rolling_horizons=(1, 24),
    )

    assert report["engine"] == "canonical PredictionEngine via forecast_site_signals"
    assert report["source_data_sha256"] == "a" * 64
    assert set(report["signals"]) == {"load", "solar", "wind", "price"}
    for signal in report["signals"].values():
        assert signal["selected_model"]
        assert signal["selection_backtest"]["fold_metrics"]
        assert len(signal["forecast_points"]) == 6
        assert set(signal["rolling_origin_candidate_evaluations"]) == {"1", "24"}
        for horizon_result in signal["rolling_origin_candidate_evaluations"].values():
            assert horizon_result["models"]
            assert horizon_result["best_by_mae"] in {
                item["model_id"] for item in horizon_result["models"]
            }
            for model in horizon_result["models"]:
                assert "bias_predicted_minus_actual" in model
                assert model["fold_metrics"]
                assert all(
                    fold["train_samples"] > 0 and fold["samples"] > 0
                    for fold in model["fold_metrics"]
                )
