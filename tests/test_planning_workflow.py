from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.canonical_run import create_run_manifest
from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
from islandos_core.planning_workflow import run_forecast_dispatch


def _inputs():
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    timestamps = tuple(start + timedelta(hours=index) for index in range(96))
    history = {
        "pv_power_kw": [max(0.0, 5.0 + 3.0 * ((i % 24) / 24)) for i in range(96)],
        "wind_power_kw": [3.0 + (i % 5) * 0.2 for i in range(96)],
        "load_kw": [8.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
        "tariff_per_kwh": [0.08 if i % 24 < 6 else 0.20 for i in range(96)],
    }
    units = {
        "pv_power_kw": "kW", "wind_power_kw": "kW",
        "load_kw": "kW", "tariff_per_kwh": "USD/kWh",
    }
    config = EnergySystemConfig(
        pv_rated_kw=10.0, wind_rated_kw=8.0, grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=20.0, max_charge_kw=5.0, max_discharge_kw=5.0,
            initial_soc=0.6,
        ),
        diesel=DieselSpec(
            rated_power_kw=10.0, variable_cost_per_kwh=0.3,
            ramp_up_kw_per_hour=10.0,
        ),
    )
    manifest = create_run_manifest(
        project_id="project-integration",
        run_id="run-integration-001",
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
    return timestamps, history, units, config, manifest


def test_manifest_bound_forecast_dispatch_produces_auditable_run_result():
    timestamps, history, units, config, manifest = _inputs()
    result = run_forecast_dispatch(
        manifest,
        timestamps=timestamps,
        history=history,
        units=units,
        energy_system_config=config,
        grid_available=[True] * 6,
        diesel_available=[True] * 6,
    )
    assert result["project_id"] == "project-integration"
    assert result["run_id"] == "run-integration-001"
    assert result["manifest_sha256"] == manifest.manifest_sha256
    assert set(result["forecast_results"]) == set(units)
    assert set(result["forecast"]["selected_models"]) == set(result["forecast_results"])
    assert len(result["forecast"]["bundle_sha256"]) == 64
    assert set(result["forecast"]["selected_models"]) == set(units)
    assert result["optimization"]["generic_prediction_handoff"]["device_write_authorized"] is False
    assert result["human_review_required"] is True
    assert result["operator_approval"] == "pending"
    assert result["device_write_authorized"] is False
    assert result["command_generated"] is False
    assert len(result["evidence_sha256"]) == 64


def test_workflow_fails_closed_when_input_contract_differs_from_manifest():
    timestamps, history, units, config, manifest = _inputs()
    wrong_units = dict(units)
    wrong_units["load_kw"] = "MW"
    with pytest.raises(ValueError, match="units must exactly match"):
        run_forecast_dispatch(
            manifest, timestamps=timestamps, history=history, units=wrong_units,
            energy_system_config=config, grid_available=[True] * 6,
            diesel_available=[True] * 6,
        )


def test_workflow_rejects_history_shorter_than_forecast_minimum():
    timestamps, history, units, config, manifest = _inputs()
    short_timestamps = timestamps[:71]
    short_history = {key: values[:71] for key, values in history.items()}

    with pytest.raises(ValueError, match="At least 72 hourly timestamps"):
        run_forecast_dispatch(
            manifest,
            timestamps=short_timestamps,
            history=short_history,
            units=units,
            energy_system_config=config,
            grid_available=[True] * 6,
            diesel_available=[True] * 6,
        )


def test_workflow_rejects_non_contiguous_hourly_history_at_composition_boundary():
    timestamps, history, units, config, manifest = _inputs()
    malformed = list(timestamps)
    malformed[48] += timedelta(minutes=15)

    with pytest.raises(ValueError, match="contiguous hourly"):
        run_forecast_dispatch(
            manifest,
            timestamps=malformed,
            history=history,
            units=units,
            energy_system_config=config,
            grid_available=[True] * 6,
            diesel_available=[True] * 6,
        )


def test_workflow_rejects_naive_history_timestamp_at_composition_boundary():
    timestamps, history, units, config, manifest = _inputs()
    malformed = list(timestamps)
    malformed[0] = malformed[0].replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        run_forecast_dispatch(
            manifest,
            timestamps=malformed,
            history=history,
            units=units,
            energy_system_config=config,
            grid_available=[True] * 6,
            diesel_available=[True] * 6,
        )


def test_workflow_rejects_signal_history_length_mismatch_before_forecasting():
    timestamps, history, units, config, manifest = _inputs()
    malformed = dict(history)
    malformed["wind_power_kw"] = malformed["wind_power_kw"][:-1]

    with pytest.raises(ValueError, match="wind_power_kw must have one value for every timestamp"):
        run_forecast_dispatch(
            manifest,
            timestamps=timestamps,
            history=malformed,
            units=units,
            energy_system_config=config,
            grid_available=[True] * 6,
            diesel_available=[True] * 6,
        )

