"""Smoke test for the interactive multi-resource energy-system lab."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_multi_resource_energy_system_lab_renders_default_synthetic_case():
    page = (
        Path(__file__).resolve().parents[1]
        / "pages"
        / "5_Energy_System_Lab.py"
    )
    app = AppTest.from_file(str(page), default_timeout=30).run()

    assert not app.exception
    assert len(app.metric) >= 2
    assert any("Multi-Resource Energy System Lab" in item.value for item in app.title)
