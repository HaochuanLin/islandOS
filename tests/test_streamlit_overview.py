from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_overview_renders_without_exceptions():
    """The default public entry page must render before a user starts navigating."""
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=60).run()

    assert not app.exception, "\n".join(str(item) for item in app.exception)
