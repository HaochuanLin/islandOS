"""The forecast lab must be demonstrable without an upload, and the demo must be labelled."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from islandos_core.demo_datasets import synthetic_forecast_history_csv
from islandos_core.onboarding import _split_header_unit, inspect_csv_bytes
from islandos_core.prediction_adapter import build_forecast_request
from islandos_core.prediction_engine import PredictionEngine

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FILE = REPO_ROOT / "app.py"


@pytest.fixture(scope="module")
def demo_report():
    return inspect_csv_bytes(
        synthetic_forecast_history_csv(),
        source_type="synthetic",
        source_name="islandos_synthetic_forecast_demo.csv",
    )


def test_demo_history_is_import_clean(demo_report):
    assert demo_report["status"] == "valid"
    assert demo_report["row_count"] == 168
    assert demo_report["error_count"] == 0 and demo_report["warning_count"] == 0


def test_demo_history_exposes_all_four_signals(demo_report):
    signals = {item["canonical_field"] for item in demo_report["column_mappings"]}
    assert signals == {"pv_power_kw", "wind_power_kw", "load_kw", "tariff_per_kwh"}


def test_demo_history_runs_the_forecast_pipeline(demo_report):
    request = build_forecast_request(
        synthetic_forecast_history_csv(), demo_report, signal_id="pv_power_kw", horizon=24
    )
    result = PredictionEngine().forecast(
        request, initial_history=48, backtest_horizon=24, season_length=24
    )
    assert len(result.points) == 24
    assert result.unit == "kW"


def test_price_header_with_kwh_suffix_maps_to_currency_unit(demo_report):
    mapping = next(
        item for item in demo_report["column_mappings"]
        if item["source_column"] == "electricity_price_per_kwh"
    )
    assert mapping["canonical_field"] == "tariff_per_kwh"
    assert mapping["canonical_unit"] == "currency/kWh"


def test_unknown_unit_suffix_does_not_crash_the_importer():
    assert _split_header_unit("pv_power_kva") == ("pv_power", "kVA")
    assert _split_header_unit("tariff_per_kwh") == ("tariff_per", "currency/kWh")


def test_forecast_lab_labels_the_demo_and_defaults_to_it():
    source = (REPO_ROOT / "islandos_ui" / "workspace.py").read_text(encoding="utf-8")
    assert '["Built-in synthetic demo history", "Upload a timestamped CSV"]' in source
    assert 'forecast_source_type = "synthetic"' in source
    assert "**Demo Data**" in source
    assert 'islandos_synthetic_forecast_demo.csv' in source


def test_forecast_lab_renders_and_forecasts_without_an_upload():
    app = AppTest.from_file(str(APP_FILE), default_timeout=90).run()
    app.radio[0].set_value("Forecast lab").run()
    assert not app.exception, [str(e) for e in app.exception]
    warnings = " ".join(w.value for w in app.warning)
    assert "Demo Data" in warnings
    app.button[0].click().run()
    assert not app.exception, [str(e) for e in app.exception]
    labels = {metric.label for metric in app.metric}
    assert {"Selected baseline", "Backtest MAE", "Backtest samples"} <= labels
