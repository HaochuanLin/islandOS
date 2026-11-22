"""The application/integration contract must keep naming things that exist.

`APP_INTEGRATION.md` is the layer map a second implementer reads before touching a page. It is
easy to let such a table drift: a function gets renamed, a session key changes, a page is added
and the inventory silently stops describing the repository. This file pins the three claims that
matter most — the entry points, the one shared session key, and the fact that two pages show two
different runs over the same CSV — and refuses to pass if the document starts promising an API
that does not exist.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "APP_INTEGRATION.md"
SESSION = REPO_ROOT / "islandos_core" / "session_dataset.py"
PAGES = sorted((REPO_ROOT / "pages").glob("*.py"))

# (file relative to the repository, symbol) for every entry point the inventory names.
ENTRY_POINTS = [
    ("islandos_core/app_workflow.py", "run_uploaded_strategy_comparison"),
    ("islandos_core/forecast_engine.py", "forecast_signals"),
    ("islandos_core/forecast_optimizer_adapter.py", "build_coordination_inputs"),
    ("islandos_core/forecast_optimizer_adapter.py", "build_service_equivalent_economics"),
    ("islandos_core/forecast_optimizer_adapter.py", "evaluate_forecast_stress_scenarios"),
    ("optimization/energy_system_optimizer.py", "optimize_energy_system"),
    ("islandos_core/impact_assessment.py", "assess_energy_policy_impact"),
    ("islandos_core/investment_economics.py", "evaluate_investment_economics"),
    ("islandos_core/investment_economics.py", "bind_annual_economics_to_run"),
    ("islandos_core/operator_decision.py", "build_operator_decision_record"),
    ("islandos_core/planning_workflow.py", "run_forecast_dispatch"),
    ("islandos_core/annual_operating_basis.py", "annualise_run_summary"),
    ("islandos_core/annual_operating_basis.py", "verify_annual_operating_basis"),
    ("islandos_core/flexible_tasks.py", "schedule_device_tasks"),
    ("islandos_core/flexible_task_dispatch.py", "attach_device_task_schedule"),
    ("islandos_core/energy_system.py", "dispatch_energy_system"),
    ("islandos_core/assets.py", "evaluate_asset_readiness"),
    ("islandos_core/site_inputs.py", "to_energy_system_config"),
]


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.mark.parametrize("relative_path, symbol", ENTRY_POINTS)
def test_every_entry_point_in_the_inventory_still_exists(relative_path, symbol):
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert f"def {symbol}(" in source, f"{symbol} is gone from {relative_path}"
    assert symbol in _doc(), f"APP_INTEGRATION.md stopped naming {symbol}"


def test_the_shared_session_key_is_the_one_the_code_uses():
    source = SESSION.read_text(encoding="utf-8")
    assert 'SESSION_DATASET_KEY = "islandos_session_site_dataset"' in source
    assert "islandos_session_site_dataset" in _doc()
    # The document claims this is the only payload that crosses pages; if a second
    # cross-page key appears in the pages, the inventory has to grow with it.
    assert "Exactly one payload is shared today" in _doc()


def test_the_document_says_the_two_pages_do_not_share_a_run():
    text = _doc()
    # The most misread fact in the product: 05 and 06 over the same CSV are two runs.
    assert "Two pages do not share a run" in text
    assert "run-dashboard" in text
    assert "create_run_manifest" in text


def test_every_page_in_the_repository_is_inventoried():
    text = _doc()
    for page in PAGES:
        assert page.stem in text or page.name in text, f"{page.name} is not in APP_INTEGRATION.md"


def test_the_document_does_not_promise_a_transport_that_does_not_exist():
    text = _doc()
    section = text[text.index("## 4."): text.index("## 5.")]
    assert "not implemented" in section
    assert "No HTTP surface" in text
    # And nothing in the repository claims to serve one.
    for candidate in ("islandos_api", "api_server", "openapi.json"):
        assert not (REPO_ROOT / candidate).exists(), f"{candidate} exists but the document says it does not"
