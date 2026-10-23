"""Smoke tests for the Streamlit rolling-horizon lab page."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


PAGE = Path(__file__).resolve().parents[1] / "pages" / "2_Rolling_Horizon_Lab.py"


def test_rolling_horizon_page_renders_and_runs_synthetic_comparison():
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "Rolling-horizon energy–water dispatch lab"

    app.button[0].click().run()
    assert not app.exception
    assert len(app.dataframe) >= 2
    assert "Rolling horizon" in app.dataframe[0].value.to_string()
