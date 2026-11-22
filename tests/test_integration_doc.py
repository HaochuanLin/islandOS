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


ANNUAL_INPUTS = (
    "baseline_annual_energy_cost",
    "proposed_annual_energy_cost",
    "annual_incremental_om_cost",
    "upfront_capex",
    "project_life_years",
    "discount_rate",
    "annual_energy_saving_escalation_rate",
    "annual_om_escalation_rate",
    "replacement_year",
    "residual_value",
    "service_equivalent",
)


def test_annual_basis_dictionary_names_every_input_the_screen_sends():
    text = DOC.read_text(encoding="utf-8")
    assert "### 6.4 Annual basis" in text
    for name in ANNUAL_INPUTS:
        assert name in text, f"§6.4 no longer defines {name}"
    # The dictionary must not be a paraphrase: the validated ranges stay in it.
    assert "integer 1–40" in text or "1-40" in text
    assert "fraction 0–0.5" in text or "0-0.5" in text


def test_the_dictionary_names_what_the_bills_must_never_be():
    text = DOC.read_text(encoding="utf-8")
    assert "must never be" in text
    assert "× 365" in text or "* 365" in text


def test_the_unbridged_day_to_year_gap_stays_visible():
    text = DOC.read_text(encoding="utf-8")
    # §6.5 and gap 6 both exist: dropping either would let a future implementer
    # annualise the run's day cost without noticing it was never agreed.
    assert "### 6.5" in text
    assert "no bridge from the run's day to the annual bills" in text.lower() or "no bridge from the run's 24-hour cost" in text
