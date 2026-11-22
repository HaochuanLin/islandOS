"""INTEGRATION.md must exist and keep pointing at code that is still there."""

from pathlib import Path

from islandos_core import investment_economics, operator_decision, planning_workflow
from islandos_core.forecast_optimizer_adapter import build_service_equivalent_economics
from islandos_core.prediction_dispatch_adapter import optimize_prediction_resource_schedule

DOC = Path(__file__).resolve().parents[1] / "INTEGRATION.md"


def test_document_exists_and_names_the_four_stages():
    text = DOC.read_text(encoding="utf-8")
    assert "## 1. Stage map" in text
    for stage in ("Predict", "Optimize", "Economics", "Decision"):
        assert f"| {stage} " in text or f"{stage} |" in text


def test_document_points_at_the_real_entry_points():
    text = DOC.read_text(encoding="utf-8")
    for symbol in (
        "run_forecast_dispatch",
        "build_service_equivalent_economics",
        "evaluate_investment_economics",
        "build_operator_decision_record",
        "forecast_site_signals",
    ):
        assert symbol in text, f"INTEGRATION.md no longer mentions {symbol}"
    # ...and that those callables still exist under the names the document cites.
    assert callable(planning_workflow.run_forecast_dispatch)
    assert callable(build_service_equivalent_economics)
    assert callable(investment_economics.evaluate_investment_economics)
    assert callable(operator_decision.build_operator_decision_record)
    assert callable(optimize_prediction_resource_schedule)


def test_document_records_the_gaps_it_knows_about():
    text = DOC.read_text(encoding="utf-8")
    assert "Gaps between contract and code" in text
