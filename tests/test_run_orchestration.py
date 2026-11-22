"""The orchestration layer must produce what the page's own call sequence produced.

Each test runs the sequence twice — once through `islandos_core.run_orchestration`, once
inline exactly as the page used to spell it — and compares the values the page displays. If
the order, the weights or a keyword argument drifted, one of these comparisons changes.
"""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

import pytest

from islandos_core.canonical_run import create_run_manifest
from islandos_core.forecast_engine import forecast_signals
from islandos_core.forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_service_equivalent_economics,
    evaluate_forecast_stress_scenarios,
)
from islandos_core.impact_assessment import assess_energy_policy_impact
from islandos_core.planning_workflow import run_forecast_dispatch
from islandos_core.run_orchestration import run_customer_dashboard, run_joint_optimizer
from islandos_core.site_inputs import SiteAssumptions
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
OPTIMIZER_HISTORY = {
    "pv_power_kw": DASHBOARD_HISTORY["pv_power"],
    "wind_power_kw": DASHBOARD_HISTORY["wind_power"],
    "load_kw": DASHBOARD_HISTORY["essential_load"],
    "tariff_per_kwh": DASHBOARD_HISTORY["electricity_price"],
}
OPTIMIZER_UNITS = {
    "pv_power_kw": "kW", "wind_power_kw": "kW", "load_kw": "kW", "tariff_per_kwh": "USD/kWh",
}


def _site(*, diesel_rated_kw: float = 0.0, diesel_cost: float = 0.0) -> SiteAssumptions:
    return SiteAssumptions(
        pv_rated_kw=10.0,
        wind_rated_kw=8.0,
        grid_import_limit_kw=20.0,
        battery_capacity_kwh=20.0,
        battery_power_kw=5.0,
        battery_initial_soc=0.60,
        battery_min_soc=0.10,
        battery_max_soc=0.95,
        diesel_rated_kw=diesel_rated_kw,
        diesel_variable_cost_per_kwh=diesel_cost,
    )


def _manifest(units):
    return create_run_manifest(
        project_id="project-orchestration",
        run_id="run-orchestration-001",
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


def test_the_dashboard_orchestration_matches_the_pages_own_sequence():
    site = _site()
    orchestrated = run_customer_dashboard(
        history_stamps=TIMESTAMPS,
        history=DASHBOARD_HISTORY,
        units=DASHBOARD_UNITS,
        site=site,
        currency="USD",
        cost_priority=0.7,
        provenance="Synthetic demonstration data",
    )

    config = site.to_energy_system_config()
    bundle = forecast_signals(
        TIMESTAMPS, DASHBOARD_HISTORY, DASHBOARD_UNITS, horizon=24,
        non_negative_signals=("pv_power", "wind_power", "essential_load"),
    )
    coordinated = build_coordination_inputs(
        bundle, grid_available=[True] * 24, price_unit="USD/kWh",
    )
    weights = OptimizationWeights(cost=0.7, reliability=0.3, curtailment=0.0, battery_wear=0.0)
    result = optimize_energy_system(coordinated.inputs, config, weights=weights)
    economics = build_service_equivalent_economics(result)
    stress = evaluate_forecast_stress_scenarios(coordinated, config)
    impact = assess_energy_policy_impact(
        coordinated.inputs, config, currency="USD",
        evaluation_period="24-hour dispatch scenario",
        data_provenance="Synthetic demonstration data",
    )

    assert asdict(orchestrated["config"]) == asdict(config)
    assert orchestrated["bundle"].input_history_sha256 == bundle.input_history_sha256
    assert orchestrated["weights"].cost == pytest.approx(weights.cost)
    assert orchestrated["weights"].reliability == pytest.approx(weights.reliability)
    assert orchestrated["weights"].curtailment == weights.curtailment
    assert orchestrated["weights"].battery_wear == weights.battery_wear
    assert orchestrated["result"]["recommendation"]["policy"] == result["recommendation"]["policy"]
    assert orchestrated["economics"]["service_equivalent"] == economics["service_equivalent"]
    assert orchestrated["economics"]["cost_comparison_valid"] == economics["cost_comparison_valid"]
    assert sorted(orchestrated["stress"]["policy_results"]) == sorted(stress["policy_results"])
    assert (
        orchestrated["paired_impact"]["gross_operating_benefit"]
        == impact["gross_operating_benefit"]
    )
    selected = next(
        row for row in orchestrated["result"]["candidates"]
        if row["policy"] == orchestrated["result"]["recommendation"]["policy"]
    )
    assert selected["summary"]["estimated_energy_cost"] == next(
        row for row in result["candidates"]
        if row["policy"] == result["recommendation"]["policy"]
    )["summary"]["estimated_energy_cost"]


def test_the_joint_optimizer_orchestration_matches_run_forecast_dispatch():
    manifest = _manifest(OPTIMIZER_UNITS)
    diesel_site = _site(diesel_rated_kw=10.0, diesel_cost=0.30)
    orchestrated = run_joint_optimizer(
        run_manifest=manifest,
        timestamps=TIMESTAMPS,
        history=OPTIMIZER_HISTORY,
        units=OPTIMIZER_UNITS,
        config=diesel_site.to_energy_system_config(),
        grid_available=[True] * 6,
        diesel_available=[True] * 6,
    )

    direct = run_forecast_dispatch(
        manifest,
        timestamps=TIMESTAMPS,
        history=OPTIMIZER_HISTORY,
        units=OPTIMIZER_UNITS,
        energy_system_config=diesel_site.to_energy_system_config(),
        grid_available=[True] * 6,
        diesel_available=[True] * 6,
    )

    assert orchestrated["planning_run"]["run_id"] == direct["run_id"]
    assert orchestrated["planning_run"]["manifest_sha256"] == direct["manifest_sha256"]
    assert orchestrated["planning_run"]["evidence_sha256"] == direct["evidence_sha256"]
    assert orchestrated["planning_run"]["decision_record"]["status"] == direct["decision_record"]["status"]
    assert (
        orchestrated["result"]["recommendation"]["dispatch"]["summary"]["estimated_energy_cost"]
        == direct["optimization"]["recommendation"]["dispatch"]["summary"]["estimated_energy_cost"]
    )
    assert (
        orchestrated["result"]["recommendation"]["dispatch"]["summary"]["unmet_load_kwh"]
        == direct["optimization"]["recommendation"]["dispatch"]["summary"]["unmet_load_kwh"]
    )
    assert orchestrated["target_timestamps"] == tuple(
        point.timestamp for point in direct["forecast_results"]["pv_power_kw"].points
    )
    assert orchestrated["handoff"]["device_write_authorized"] == direct["optimization"][
        "generic_prediction_handoff"
    ]["device_write_authorized"]


def test_the_orchestration_module_needs_no_streamlit():
    completed = subprocess.run(
        [sys.executable, "-c",
         "import sys; import islandos_core.run_orchestration; "
         "assert 'streamlit' not in sys.modules; print('ok')"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
