"""Regression coverage for source provenance in the primary Streamlit app."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_main_app_exports_include_visible_provenance():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception

    app.radio[0].set_value("Strategy simulator").run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception

    captions = [element.value for element in app.get("caption")]
    assert any("Source type: `synthetic`" in value for value in captions)
    hashes = [element.value for element in app.get("code")]
    assert any(len(value) == 64 for value in hashes)

    exports = app.get("download_button")
    labels = [element.label for element in exports]
    assert any("strategy summary (with provenance)" in label for label in labels)
    assert any("timestep audit (with provenance)" in label for label in labels)
