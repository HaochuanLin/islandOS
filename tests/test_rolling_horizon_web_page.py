"""Smoke tests for the Streamlit rolling-horizon lab page."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


PAGE = Path(__file__).resolve().parents[1] / "pages" / "2_Rolling_Horizon_Lab.py"


def test_rolling_horizon_page_renders_and_runs_synthetic_comparison():
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "Rolling-horizon energy–water dispatch lab"

    provenance_hashes = app.get("code")
    assert len(provenance_hashes) == 1
    assert len(provenance_hashes[0].value) == 64
    captions = [element.value for element in app.get("caption")]
    assert any("Source type: `synthetic`" in value for value in captions)
    assert any("UTC coverage:" in value for value in captions)

    app.button[0].click().run()
    assert not app.exception
    frames = [element.value for element in app.dataframe]
    summary = next(frame for frame in frames if "policy" in frame.columns)
    assert len(summary) == 4
    assert "Rolling horizon" in summary["policy"].tolist()

    exports = app.get("download_button")
    assert len(exports) == 2
    assert all("with provenance" in element.label for element in exports)
