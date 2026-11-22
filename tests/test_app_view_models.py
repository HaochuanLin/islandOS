"""The view-model contracts, checked against real core output rather than hand-built dicts.

Everything here runs the actual pipeline — `forecast_signals` + `optimize_energy_system` for the
dashboard shape, `run_forecast_dispatch` for the optimizer shape — and then asks the view model to
describe it. That is deliberate: a view model tested against a fixture it built itself would only
prove that the fixture matches the test.
"""

from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
from pathlib import Path

import pytest

from islandos_core.app_view_models import (
    ANNUAL_BASIS_FIELDS,
    ANNUAL_PROJECTION_FIELDS,
    CONTRACT_VERSION,
    HISTORY_FIELDS,
    PAGE_CUSTOMER_DASHBOARD,
    PAGE_JOINT_OPTIMIZER,
    REQUEST_FIELDS,
    RESULT_SUMMARY_FIELDS,
    RUN_REQUEST_SITE_FIELDS,
    build_annual_projection,
    build_run_request,
    build_run_result_summary,
    to_json,
)
from islandos_core.annual_operating_basis import annualise_run_summary, verify_annual_operating_basis
from islandos_core.canonical_run import create_run_manifest
from islandos_core.energy_system import EnergySystemConfig, dispatch_energy_system
from islandos_core.forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_service_equivalent_economics,
)
from islandos_core.forecast_engine import forecast_signals
from islandos_core.planning_workflow import run_forecast_dispatch
from islandos_core.site_inputs import DEFAULT_SITE, SiteAssumptions, default_site
from optimization.energy_system_optimizer import OptimizationWeights, optimize_energy_system

REPO_ROOT = Path(__file__).resolve().parents[1]

START = datetime(2026, 11, 1, tzinfo=timezone.utc)
TIMESTAMPS = tuple(START + timedelta(hours=index) for index in range(96))
DASHBOARD_HISTORY = {
    "pv_power": [max(0.0, 5.0 + 3.0 * ((i % 24) / 24)) for i in range(96)],
    "wind_power": [3.0 + (i % 5) * 0.2 for i in range(96)],
    "essential_load": [8.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
    "electricity_price": [0.08 if i % 24 < 6 else 0.20 for i in range(96)],
}
DASHBOARD_UNITS = {
    "pv_power": "kW",
    "wind_power": "kW",
    "essential_load": "kW",
    "electricity_price": "USD/kWh",
}


def _site(pv: float = 10.0, battery_power: float = 5.0) -> SiteAssumptions:
    return SiteAssumptions(
        pv_rated_kw=pv,
        wind_rated_kw=8.0,
        grid_import_limit_kw=20.0,
        battery_capacity_kwh=20.0,
        battery_power_kw=battery_power,
        battery_initial_soc=0.60,
        battery_min_soc=0.10,
        battery_max_soc=0.95,
        diesel_rated_kw=0.0,
        diesel_variable_cost_per_kwh=0.0,
    )


@pytest.fixture(scope="module")
def dashboard_run():
    bundle = forecast_signals(
        TIMESTAMPS, DASHBOARD_HISTORY, DASHBOARD_UNITS, horizon=24,
        non_negative_signals=("pv_power", "wind_power", "essential_load"),
    )
    coordinated = build_coordination_inputs(
        bundle, grid_available=[True] * 24, price_unit="USD/kWh",
    )
    weights = OptimizationWeights(cost=0.7, reliability=0.3, curtailment=0.0, battery_wear=0.0)
    result = optimize_energy_system(
        coordinated.inputs, _site().with_overrides(diesel_rated_kw=0.0).to_energy_system_config(),
        weights=weights,
    )
    economics = build_service_equivalent_economics(result)
    return result, economics


@pytest.fixture(scope="module")
def optimizer_run():
    history = {
        "pv_power_kw": [max(0.0, 5.0 + 3.0 * ((i % 24) / 24)) for i in range(96)],
        "wind_power_kw": [3.0 + (i % 5) * 0.2 for i in range(96)],
        "load_kw": [8.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
        "tariff_per_kwh": [0.08 if i % 24 < 6 else 0.20 for i in range(96)],
    }
    units = {"pv_power_kw": "kW", "wind_power_kw": "kW", "load_kw": "kW", "tariff_per_kwh": "USD/kWh"}
    config = _site().with_overrides(
        diesel_rated_kw=10.0, diesel_variable_cost_per_kwh=0.30,
    ).to_energy_system_config()
    manifest = create_run_manifest(
        project_id="project-view-models",
        run_id="run-view-model-001",
        site_ref="synthetic-site",
        created_at_utc="2026-11-18T00:00:00Z",
        dataset_sha256="a" * 64,
        dataset_schema_version="1.0",
        source_type="synthetic",
        site_configuration_version="1",
        site_configuration_sha256="b" * 64,
        required_signals=units,
        forecast_horizon_hours=6,
        optimizer_id="prediction_resource_dispatch",
        optimizer_version="current",
        optimizer_settings={"population_size": 4, "generations": 1, "seed": 31},
        scenario_assumptions={"grid_available": [True] * 6, "diesel_available": [True] * 6},
        forecast_settings={"backtest_horizon": 6, "season_length": 24, "confidence_level": 0.90},
    )
    planning_run = run_forecast_dispatch(
        manifest, timestamps=TIMESTAMPS, history=history, units=units,
        energy_system_config=config, grid_available=[True] * 6, diesel_available=[True] * 6,
    )
    return planning_run, planning_run["optimization"]


def _dashboard_request(site=None):
    return build_run_request(
        page=PAGE_CUSTOMER_DASHBOARD,
        site=site or _site(),
        timestamps=TIMESTAMPS,
        history=DASHBOARD_HISTORY,
        units=DASHBOARD_UNITS,
        page_settings={"demand_scale": 1.0, "tariff_scale": 1.0, "cost_priority": 0.7},
        run_settings={
            "currency": "USD",
            "investment": {
                "baseline_annual_energy_cost": 120000.0,
                "proposed_annual_energy_cost": 84000.0,
                "annual_incremental_om_cost": 6000.0,
                "upfront_capex": 180000.0,
                "project_life_years": 10.0,
                "discount_rate": 0.08,
                "annual_energy_saving_escalation_rate": 0.0,
                "annual_om_escalation_rate": 0.0,
            },
        },
        provenance="Synthetic demonstration data",
        source_sha256=None,
    )


def _optimizer_request(site=None):
    return build_run_request(
        page=PAGE_JOINT_OPTIMIZER,
        site=site or _site(),
        timestamps=TIMESTAMPS,
        history={
            "pv_power_kw": DASHBOARD_HISTORY["pv_power"],
            "wind_power_kw": DASHBOARD_HISTORY["wind_power"],
            "load_kw": DASHBOARD_HISTORY["essential_load"],
            "tariff_per_kwh": DASHBOARD_HISTORY["electricity_price"],
        },
        units={"pv_power_kw": "kW", "wind_power_kw": "kW", "load_kw": "kW", "tariff_per_kwh": "USD/kWh"},
        page_settings={},
        run_settings={
            "currency": "USD",
            "optimizer_settings": {"population_size": 12, "generations": 5, "seed": 20261113},
            "availability": {"grid_all_hours": True, "diesel_all_hours": True},
        },
        provenance="Synthetic demonstration data",
        source_sha256="c8dbb28c" + "0" * 56,
    )


def test_the_view_model_module_needs_no_streamlit():
    completed = subprocess.run(
        [sys.executable, "-c",
         "import sys; import islandos_core.app_view_models as m; "
         "assert 'streamlit' not in sys.modules; print(m.CONTRACT_VERSION)"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    source = (REPO_ROOT / "islandos_core" / "app_view_models.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source and "from streamlit" not in source


def test_every_contract_is_json_serialisable(dashboard_run, optimizer_run):
    result, economics = dashboard_run
    views = [
        _dashboard_request(),
        _optimizer_request(),
        build_run_result_summary(
            page=PAGE_CUSTOMER_DASHBOARD, result=result, economics=economics, currency="USD",
        ),
    ]
    planning_run, optimizer_result = optimizer_run
    views.append(
        build_run_result_summary(
            page=PAGE_JOINT_OPTIMIZER, result=optimizer_result, planning_run=planning_run,
            currency="USD",
        )
    )
    dispatch = optimizer_result["recommendation"]["dispatch"]["summary"]
    record = annualise_run_summary(
        dispatch,
        dispatch_rows=optimizer_result["recommendation"]["dispatch"]["rows"],
        simulated_hours=len(planning_run["forecast_results"]["pv_power_kw"].points),
        days_equivalent_per_year=365,
        run_id=planning_run["run_id"],
        manifest_sha256=planning_run["manifest_sha256"],
        data_provenance="Synthetic demonstration data",
        summary_source="recommended schedule's own nominal dispatch summary",
    )
    views.append(build_annual_projection(record, currency="USD"))
    for view in views:
        assert json.loads(to_json(view)) == json.loads(json.dumps(view, sort_keys=True))


def test_the_request_contract_keeps_site_page_and_run_blocks_distinct():
    dashboard = _dashboard_request()
    optimizer = _optimizer_request()
    assert dashboard["schema_version"] == CONTRACT_VERSION == optimizer["schema_version"]
    assert dashboard["page"] == "customer_dashboard"
    assert optimizer["page"] == "joint_resource_optimizer"
    # Site block is shared vocabulary; neither page may smuggle a page/run setting into it.
    assert set(dashboard["site"]) == set(DEFAULT_SITE) | {"digest"}
    assert set(optimizer["site"]) == set(DEFAULT_SITE) | {"digest"}
    assert dashboard["site"] == optimizer["site"]
    # Page-specific settings exist only where the page has them.
    assert set(dashboard["page_settings"]) == {"demand_scale", "tariff_scale", "cost_priority"}
    assert optimizer["page_settings"] == {}
    # Run-specific settings keep their own names instead of one merged bag.
    assert set(dashboard["run_settings"]) == {"currency", "investment"}
    assert set(optimizer["run_settings"]) == {"currency", "optimizer_settings", "availability"}
    # History: units match signals, and hour_count is the series length, not a guess.
    for view in (dashboard, optimizer):
        assert set(view["history"]["units"]) == set(view["history"]["signals"])
        assert view["history"]["hour_count"] == 96
        assert all(len(series) == 96 for series in view["history"]["signals"].values())


def test_the_result_summaries_describe_two_different_runs(dashboard_run, optimizer_run):
    result, economics = dashboard_run
    dashboard = build_run_result_summary(
        page=PAGE_CUSTOMER_DASHBOARD, result=result, economics=economics, currency="USD",
    )
    planning_run, optimizer_result = optimizer_run
    optimizer = build_run_result_summary(
        page=PAGE_JOINT_OPTIMIZER, result=optimizer_result, planning_run=planning_run, currency="USD",
    )
    # The dashboard's optimization run is not the run its investment screen cites, so it
    # carries no run identity at all; the optimizer summary carries the canonical run's.
    assert dashboard["run_id"] is None and dashboard["manifest_sha256"] is None
    assert optimizer["run_id"] == planning_run["run_id"]
    assert optimizer["manifest_sha256"] == planning_run["manifest_sha256"]
    assert optimizer["evidence_sha256"] == planning_run["evidence_sha256"]
    assert dashboard["run_id"] != optimizer["run_id"]
    # Values are copied from the run, never recomputed here.
    policy = result["recommendation"]["policy"]
    selected = next(row for row in result["candidates"] if row["policy"] == policy)
    assert dashboard["recommended_policy"] == policy
    assert dashboard["estimated_24h_energy_cost"] == selected["summary"]["estimated_energy_cost"]
    assert dashboard["unmet_load_kwh"] == selected["summary"]["unmet_load_kwh"]
    assert dashboard["service_equivalent"] == economics["service_equivalent"]


def test_the_dashboard_savings_claim_stays_behind_the_service_gate(dashboard_run):
    result, economics = dashboard_run
    gated = {**economics, "service_equivalent": False}
    view = build_run_result_summary(
        page=PAGE_CUSTOMER_DASHBOARD, result=result, economics=gated, currency="USD",
    )
    assert view["savings_claim_withheld"] is True
    assert view["service_equivalent"] is False
    # The number is still reported, and the view says the claim is withheld, so a client
    # cannot show it as a saving by reading the field alone.
    comparable = build_run_result_summary(
        page=PAGE_CUSTOMER_DASHBOARD, result=result, economics=economics, currency="USD",
    )
    assert comparable["savings_claim_withheld"] == (
        not (economics["service_equivalent"] and economics["cost_comparison_valid"])
    )


def test_the_optimizer_summary_keeps_null_policy_distinguishable(optimizer_run):
    planning_run, optimizer_result = optimizer_run
    view = build_run_result_summary(
        page=PAGE_JOINT_OPTIMIZER, result=optimizer_result, planning_run=planning_run, currency="USD",
    )
    # This optimizer returns no policy name; the label the page shows is explicit, and the
    # machine field stays null instead of pretending a policy was selected.
    assert view["recommended_policy"] is None
    assert view["recommended_policy_label"] == "Optimizer Recommendation"
    assert view["decision_record_status"] == planning_run["decision_record"]["status"]
    assert view["physical_audit_passed"] is True
    assert view["scenarios_audited"] == sorted(
        optimizer_result["recommendation"]["scenario_results"]
    )


def test_the_annual_projection_view_carries_its_basis_and_refuses_a_tampered_record(optimizer_run):
    planning_run, optimizer_result = optimizer_run
    dispatch = optimizer_result["recommendation"]["dispatch"]
    record = annualise_run_summary(
        dispatch["summary"],
        dispatch_rows=dispatch["rows"],
        simulated_hours=24,
        days_equivalent_per_year=200,
        run_id=planning_run["run_id"],
        manifest_sha256=planning_run["manifest_sha256"],
        data_provenance="Synthetic demonstration data",
        summary_source="recommended schedule's own nominal dispatch summary",
    )
    view = build_annual_projection(record, currency="USD")
    assert view["basis"]["days_equivalent_per_year"] == 200
    assert view["basis"]["bill"] is False and view["basis"]["site_validated"] is False
    assert view["figures"] == record["figures"]
    assert set(view["definitions"]) == set(record["definitions"])
    assert view["projection_sha256"] == record["annualisation_sha256"]
    assert view["currency"] == "USD"

    tampered = {**record, "figures": {**record["figures"], "annual_energy_cost": 1.0}}
    with pytest.raises(ValueError, match="does not verify"):
        build_annual_projection(tampered)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda s: {**s, "demand_scale": None}, "demand_scale"),
        (lambda r: {**r, "investment": {k: v for k, v in r["investment"].items() if k != "discount_rate"}},
         "discount_rate"),
        (lambda r: {**r, "currency": "  "}, "currency"),
    ],
)
def test_missing_or_empty_inputs_fail_explicitly(mutate, message):
    settings = {"demand_scale": 1.0, "tariff_scale": 1.0, "cost_priority": 0.7}
    run = {
        "currency": "USD",
        "investment": {
            "baseline_annual_energy_cost": 120000.0, "proposed_annual_energy_cost": 84000.0,
            "annual_incremental_om_cost": 6000.0, "upfront_capex": 180000.0,
            "project_life_years": 10.0, "discount_rate": 0.08,
            "annual_energy_saving_escalation_rate": 0.0, "annual_om_escalation_rate": 0.0,
        },
    }
    with pytest.raises(ValueError, match=message):
        build_run_request(
            page=PAGE_CUSTOMER_DASHBOARD,
            site=_site(),
            timestamps=TIMESTAMPS,
            history=DASHBOARD_HISTORY,
            units=DASHBOARD_UNITS,
            page_settings=mutate(settings) if "scale" in message else settings,
            run_settings=mutate(run),
            provenance="Synthetic demonstration data",
            source_sha256=None,
        )


def test_the_request_refuses_an_unknown_page_key_or_mismatched_series():
    with pytest.raises(ValueError, match="page must be one of"):
        build_run_request(
            page="something_else", site=_site(), timestamps=TIMESTAMPS,
            history=DASHBOARD_HISTORY, units=DASHBOARD_UNITS,
            page_settings={}, run_settings={"currency": "USD"},
            provenance="Synthetic demonstration data", source_sha256=None,
        )
    with pytest.raises(ValueError, match="unknown fields"):
        build_run_request(
            page=PAGE_JOINT_OPTIMIZER, site=_site(), timestamps=TIMESTAMPS,
            history=DASHBOARD_HISTORY,
            units=DASHBOARD_UNITS, page_settings={"cost_priority": 0.7},
            run_settings={"currency": "USD"},
            provenance="Synthetic demonstration data", source_sha256=None,
        )
    ragged = {**DASHBOARD_HISTORY, "pv_power": DASHBOARD_HISTORY["pv_power"][:50]}
    with pytest.raises(ValueError, match="one length"):
        build_run_request(
            page=PAGE_CUSTOMER_DASHBOARD, site=_site(), timestamps=TIMESTAMPS,
            history=ragged, units=DASHBOARD_UNITS,
            page_settings={"demand_scale": 1.0, "tariff_scale": 1.0, "cost_priority": 0.7},
            run_settings={
                "currency": "USD",
                "investment": {
                    "baseline_annual_energy_cost": 1.0, "proposed_annual_energy_cost": 1.0,
                    "annual_incremental_om_cost": 0.0, "upfront_capex": 1.0,
                    "project_life_years": 10.0, "discount_rate": 0.08,
                    "annual_energy_saving_escalation_rate": 0.0,
                    "annual_om_escalation_rate": 0.0,
                },
            },
            provenance="Synthetic demonstration data", source_sha256=None,
        )


def test_the_site_block_is_the_site_module_not_a_copy_of_defaults():
    view = _optimizer_request(default_site())
    assert {key: view["site"][key] for key in DEFAULT_SITE} == DEFAULT_SITE
    assert view["site"]["digest"] == default_site().digest()
    with pytest.raises(ValueError, match="SiteAssumptions"):
        build_run_request(
            page=PAGE_JOINT_OPTIMIZER, site=DEFAULT_SITE, timestamps=TIMESTAMPS,
            history=DASHBOARD_HISTORY,
            units=DASHBOARD_UNITS, page_settings={},
            run_settings={
                "currency": "USD",
                "optimizer_settings": {"population_size": 12, "generations": 5, "seed": 1},
                "availability": {"grid_all_hours": True, "diesel_all_hours": True},
            },
            provenance="Synthetic demonstration data", source_sha256=None,
        )


def test_synthetic_provenance_survives_into_every_contract(dashboard_run, optimizer_run):
    assert _dashboard_request()["history"]["provenance"] == "Synthetic demonstration data"
    assert _optimizer_request()["history"]["provenance"] == "Synthetic demonstration data"
    planning_run, optimizer_result = optimizer_run
    dispatch = optimizer_result["recommendation"]["dispatch"]
    record = annualise_run_summary(
        dispatch["summary"], dispatch_rows=dispatch["rows"], simulated_hours=24,
        days_equivalent_per_year=365, run_id=planning_run["run_id"],
        manifest_sha256=planning_run["manifest_sha256"],
        data_provenance="Synthetic demonstration data",
        summary_source="recommended schedule's own nominal dispatch summary",
    )
    assert verify_annual_operating_basis(record)["valid"] is True
    assert build_annual_projection(record)["data_provenance"] == "Synthetic demonstration data"


def test_the_declared_field_sets_match_what_the_builders_return(dashboard_run, optimizer_run):
    dashboard_result, economics = dashboard_run
    request = _dashboard_request()
    assert tuple(request) == REQUEST_FIELDS
    assert tuple(request["site"]) == RUN_REQUEST_SITE_FIELDS
    assert tuple(request["history"]) == HISTORY_FIELDS

    summary = build_run_result_summary(
        page=PAGE_CUSTOMER_DASHBOARD, result=dashboard_result, economics=economics, currency="USD",
    )
    assert tuple(summary) == RESULT_SUMMARY_FIELDS

    planning_run, optimizer_result = optimizer_run
    optimizer_summary = build_run_result_summary(
        page=PAGE_JOINT_OPTIMIZER, result=optimizer_result, planning_run=planning_run,
        currency="USD",
    )
    assert tuple(optimizer_summary) == RESULT_SUMMARY_FIELDS

    dispatch = optimizer_result["recommendation"]["dispatch"]
    record = annualise_run_summary(
        dispatch["summary"], dispatch_rows=dispatch["rows"], simulated_hours=24,
        days_equivalent_per_year=365, run_id=planning_run["run_id"],
        manifest_sha256=planning_run["manifest_sha256"],
        data_provenance="Synthetic demonstration data",
        summary_source="recommended schedule's own nominal dispatch summary",
    )
    annual = build_annual_projection(record)
    assert tuple(annual) == ANNUAL_PROJECTION_FIELDS
    assert tuple(annual["basis"]) == ANNUAL_BASIS_FIELDS


def test_the_contract_version_only_moves_forward():
    assert isinstance(CONTRACT_VERSION, int) and not isinstance(CONTRACT_VERSION, bool)
    assert CONTRACT_VERSION >= 1


def test_the_pages_publish_the_same_views_they_render():
    dashboard_source = (
        REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"
    ).read_text(encoding="utf-8")
    optimizer_source = (
        REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"
    ).read_text(encoding="utf-8")
    for source in (dashboard_source, optimizer_source):
        assert '"application_views"' in source
        assert '"request": run_request_view' in source
        assert '"result": result_view' in source
    assert '"annual": annual_view' in optimizer_source
    # The annual view must exist even when the reader leaves the projection withheld, or
    # the report would NameError on the default path.
    assert optimizer_source.count("annual_view = None") == 1
    assert "annual_view = build_annual_projection(" in optimizer_source
