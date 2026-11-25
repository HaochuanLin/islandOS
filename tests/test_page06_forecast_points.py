"""T3 page test: 06 exposes forecast points and intervals without refitting."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"


def test_page_source_order_and_forecast_point_contract():
    source = PAGE.read_text(encoding="utf-8")

    prediction_table = source.index('st.subheader("Prediction engine")')
    forecast_points = source.index('st.subheader("Forecast points and intervals")')
    recommended = source.index('st.subheader("Recommended joint schedule")')
    assert prediction_table < forecast_points < recommended

    assert "Inputs and assumptions used by this run" in source
    assert "selected_forecast.points" in source
    assert "point.predicted_value" in source
    assert "point.lower_bound" in source
    assert "point.upper_bound" in source
    assert "st.line_chart(points_frame)" in source
    assert "No forecast points returned for this signal" in source
    assert "The band is an empirical backtest interval" in source
    assert "model_id" in source and "confidence_level" in source
    assert "interval_method" in source and "interval_calibration_samples" in source


def test_page_renders_forecast_points_and_keeps_model_table():
    app = AppTest.from_file(str(PAGE), default_timeout=120).run()
    assert not app.exception, "\n".join(str(exc) for exc in app.exception)

    subheaders = [element.value for element in app.subheader]
    assert "Prediction engine" in subheaders
    assert "Forecast points and intervals" in subheaders
    assert "Recommended joint schedule" in subheaders

    signal_box = next(
        element for element in app.selectbox if element.label == "Forecast signal"
    )
    assert signal_box.options, "forecast signal selectbox must list at least one signal"
    assert signal_box.value in {"load_kw", "pv_power_kw", "tariff_per_kwh", "wind_power_kw"}

    assert len(app.table) >= 2, "expected prediction metrics plus point-by-point table"
    assert any("Inputs and assumptions used by this run" in element.label for element in app.expander)
