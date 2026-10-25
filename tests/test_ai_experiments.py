from __future__ import annotations

import csv
import json

import pytest

from experiments.renewable_surplus_forecast_experiment import (
    generate_synthetic_series,
    metric,
    run as run_forecast_experiment,
    walk_forward_forecasts,
)
from experiments.telemetry_anomaly_experiment import (
    generate_telemetry,
    rolling_median_mad_flags,
    run as run_anomaly_experiment,
)
from experiments.structured_recommendation_explanations import evaluate_recommendation


def test_synthetic_surplus_series_is_deterministic_and_marked_by_schema():
    first = generate_synthetic_series(20261021, hours=14 * 24 + 48)
    second = generate_synthetic_series(20261021, hours=14 * 24 + 48)
    assert first == second
    assert len(first) == 14 * 24 + 48
    assert {"timestamp_utc", "actual_surplus_kw", "water_demand_m3"} <= set(first[0])
    assert all(row["actual_surplus_kw"] >= 0 for row in first)


def test_walk_forward_forecast_baselines_cover_test_window():
    rows = generate_synthetic_series(20261021)
    forecasts = walk_forward_forecasts(rows, 20261021)
    expected = set(range(14 * 24, len(rows)))
    assert set(forecasts["persistence"]) == expected
    assert set(forecasts["seasonal_naive_24h"]) == expected
    assert all(value >= 0 for value in forecasts["persistence"].values())
    assert all(value >= 0 for value in forecasts["seasonal_naive_24h"].values())
    # sklearn is optional; if installed the candidate must cover the same window.
    try:
        import sklearn  # noqa: F401
    except ImportError:
        assert not forecasts["hist_gradient_boosting"]
    else:
        assert set(forecasts["hist_gradient_boosting"]) == expected


def test_metric_calculation_is_finite_and_aligned():
    result = metric([1.0, 3.0], [2.0, 2.0])
    assert result == {"mae_kw": 1.0, "rmse_kw": 1.0, "bias_kw": 0.0}


def test_forecast_experiment_connects_to_existing_ro_simulator(tmp_path):
    report = run_forecast_experiment(tmp_path / "forecast", seeds=(20261021,))
    assert report["status"] == "synthetic_forecast_experiment_completed"
    assert report["data_status"] == "synthetic / scenario assumption, not measured real-world data"
    assert (tmp_path / "forecast" / "forecast_metrics.csv").is_file()
    assert (tmp_path / "forecast" / "dispatch_comparison.csv").is_file()
    manifest = json.loads((tmp_path / "forecast" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["is_measured_site_data"] is False
    assert manifest["artifacts"]["synthetic_surplus_input_seed_20261021.csv"]["sha256"]


def test_rolling_median_mad_flags_missing_and_flatline():
    flags = rolling_median_mad_flags([10.0] * 8 + [None] + [12.0] * 8)
    assert flags[8] is True
    assert any(flags[10:])


def test_synthetic_telemetry_contains_explicit_fault_labels():
    rows = generate_telemetry(20261021, hours=150)
    assert rows[85]["fault_label"] == "missing"
    assert rows[140]["fault_label"] == "spike"
    assert rows[85]["meter_kw"] is None
    assert rows[0]["is_synthetic"] is True


def test_anomaly_experiment_writes_fail_closed_review_output(tmp_path):
    report = run_anomaly_experiment(tmp_path, seed=20261021, hours=150)
    assert report["data_status"] == "synthetic / scenario assumption, not measured real-world data"
    assert report["quality_gate"]["physical_write_performed"] is False
    assert (tmp_path / "manifest.json").is_file()
    with (tmp_path / "telemetry_anomaly_results.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    missing = next(row for row in rows if row["fault_label"] == "missing")
    assert missing["review_status"] == "HOLD: data quality check failed"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["is_measured_site_data"] is False
    assert manifest["artifacts"]["synthetic_telemetry_input.csv"]["sha256"]


def _valid_inputs(**overrides):
    values = {
        "telemetry_quality_passed": True,
        "hard_constraints_passed": True,
        "available_surplus_kw": 250.0,
        "required_power_kw": 200.0,
        "water_inventory_m3": 120.0,
        "target_water_inventory_m3": 300.0,
    }
    values.update(overrides)
    return values


def test_explanation_start_is_advisory_and_auditable():
    result = evaluate_recommendation(_valid_inputs())
    assert result["reason_code"] == "START_SURPLUS_AVAILABLE_AND_WATER_BUFFER_LOW"
    assert result["recommendation"] == "START_ELIGIBLE_FOR_OPERATOR_REVIEW"
    assert result["operator_action_required"] is True
    assert result["physical_write_performed"] is False
    assert result["mode"] == "advisory_recommendation_only"


def test_bad_data_routes_to_exact_hold_reason_even_if_numeric_fields_are_missing():
    inputs = _valid_inputs(telemetry_quality_passed=False)
    inputs.pop("available_surplus_kw")
    result = evaluate_recommendation(inputs)
    assert result["reason_code"] == "HOLD_DATA_QUALITY_FAILED"
    assert result["recommendation"] == "HOLD"
    assert result["explanation_en"].startswith("HOLD: data quality check failed.")


@pytest.mark.parametrize("field,value", [
    ("available_surplus_kw", float("nan")),
    ("required_power_kw", -1.0),
    ("water_inventory_m3", True),
])
def test_explanation_rejects_invalid_numeric_inputs(field, value):
    with pytest.raises(ValueError):
        evaluate_recommendation(_valid_inputs(**{field: value}))
