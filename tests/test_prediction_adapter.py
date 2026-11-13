from datetime import datetime, timezone

import pytest

from islandos_core.onboarding import inspect_csv_bytes
from islandos_core.prediction_adapter import build_forecast_request
from islandos_core.prediction_engine import PredictionEngine


NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


def _csv(signal="load_kw", values=(10, 11, 12, 13, 14, 15)):
    header = "tariff (currency/kWh)" if signal == "tariff_per_kwh" else signal\n    rows = ["timestamp," + header]
    for index, value in enumerate(values):
        rows.append(f"2026-11-01T{index:02d}:00:00Z,{value}")
    return ("\n".join(rows) + "\n").encode()


def _report(raw, signal="load_kw"):
    return inspect_csv_bytes(raw, source_type="measured", now=NOW)


def test_onboarding_adapter_builds_forecast_and_engine_result():
    raw = _csv()
    report = _report(raw)
    request = build_forecast_request(raw, report, signal_id="load_kw", horizon=3)
    result = PredictionEngine().forecast(
        request, initial_history=3, backtest_horizon=1, season_length=3
    )
    assert result.signal_id == "load_kw"
    assert result.unit == "kW"
    assert len(result.points) == 3
    assert len(result.input_history_sha256) == 64


def test_negative_tariffs_are_preserved_as_signed_signal():
    raw = _csv("tariff_per_kwh", (0.12, -0.03, 0.08, -0.01, 0.10, 0.04))
    report = _report(raw, "tariff_per_kwh")
    assert report["error_count"] == 0
    request = build_forecast_request(raw, report, signal_id="tariff_per_kwh", horizon=2)
    assert request.non_negative is False
    assert [item.value for item in request.history][1] == -0.03


def test_missing_values_are_not_imputed():
    raw = b"timestamp,load_kw\n2026-11-01T00:00:00Z,1\n2026-11-01T01:00:00Z,\n2026-11-01T02:00:00Z,3\n"
    report = _report(raw)
    with pytest.raises(ValueError, match="blocking import errors"):
        build_forecast_request(raw, report, signal_id="load_kw")


def test_ambiguous_unit_is_blocked():
    raw = b"timestamp,load\n2026-11-01T00:00:00Z,1\n2026-11-01T01:00:00Z,2\n2026-11-01T02:00:00Z,3\n"
    report = _report(raw)
    with pytest.raises(ValueError, match="blocking import errors|explicit"):
        build_forecast_request(raw, report, signal_id="load_kw")


def test_irregular_cadence_is_rejected():
    raw = b"timestamp,load_kw\n2026-11-01T00:00:00Z,1\n2026-11-01T01:00:00Z,2\n2026-11-01T03:00:00Z,3\n"
    report = _report(raw)
    with pytest.raises(ValueError, match="regular cadence"):
        build_forecast_request(raw, report, signal_id="load_kw")
