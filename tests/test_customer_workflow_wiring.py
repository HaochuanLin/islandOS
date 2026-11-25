"""T7 wiring test: both customer pages pass the shared input fingerprint."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    "decision_dashboard": REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py",
    "joint_optimizer": REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py",
}


def test_both_pages_build_the_shared_fingerprint_before_the_workflow_note():
    source_05 = PAGES["decision_dashboard"].read_text(encoding="utf-8")
    source_06 = PAGES["joint_optimizer"].read_text(encoding="utf-8")

    for source in (source_05, source_06):
        assert "build_input_fingerprint(" in source
        assert "site_assumptions.digest()" in source
        assert "fingerprint=fingerprint" in source
        assert "Input fingerprint:" in source
        assert source.count("render_customer_workflow(") == 1

    assert 'page="decision_dashboard"' in source_05
    assert '"demand_scale": float(demand_scale)' in source_05
    assert '"tariff_scale": float(tariff_scale)' in source_05
    assert '"cost_priority": float(cost_priority)' in source_05

    assert 'page="joint_optimizer"' in source_06
    assert '"population": int(population)' in source_06
    assert '"generations": int(generations)' in source_06
    assert '"seed": int(seed)' in source_06


def test_workflow_note_renders_after_site_assumptions_are_available():
    source_05 = PAGES["decision_dashboard"].read_text(encoding="utf-8")
    source_06 = PAGES["joint_optimizer"].read_text(encoding="utf-8")

    for source in (source_05, source_06):
        site_construction = source.index("site_assumptions = SiteAssumptions(")
        workflow_call = source.index("render_customer_workflow(", site_construction)
        assert site_construction < workflow_call


def test_both_default_pages_still_render_with_the_fingerprint():
    for page in PAGES.values():
        app = AppTest.from_file(str(page), default_timeout=120).run()
        assert not app.exception, "\n".join(str(exc) for exc in app.exception)
        assert "Input fingerprint:" in " ".join(item.value for item in app.caption)
