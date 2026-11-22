from copy import deepcopy

import pytest

from islandos_core.canonical_run import (
    create_run_manifest,
    deterministic_run_id,
    verify_run_manifest,
)


def _manifest():
    return create_run_manifest(
        project_id="project-001",
        run_id="run-001",
        site_ref="site-demo",
        created_at_utc="2026-11-18T10:00:00+08:00",
        dataset_sha256="a" * 64,
        dataset_schema_version="1.0",
        source_type="synthetic",
        site_configuration_version="3",
        site_configuration_sha256="b" * 64,
        required_signals={"pv_power_kw": "kW", "load_kw": "kW", "tariff_per_kwh": "USD/kWh"},
        forecast_horizon_hours=24,
        optimizer_id="resource_dispatch",
        optimizer_version="1.2.0",
        optimizer_settings={"seed": 7, "population_size": 16},
        scenario_assumptions={"grid_available": True, "diesel_price_per_litre": 1.2},
        forecast_model_ids={"pv_power_kw": "seasonal_naive"},
    )


def test_manifest_is_deterministic_and_normalizes_timestamp_to_utc():
    first = _manifest()
    second = _manifest()
    assert first.manifest_sha256 == second.manifest_sha256
    payload = first.to_dict()
    assert payload["created_at_utc"] == "2026-11-18T02:00:00Z"
    assert verify_run_manifest(payload)["valid"] is True


def test_manifest_binds_project_data_site_forecast_and_optimizer():
    payload = _manifest().to_dict()
    assert payload["project_id"] == "project-001"
    assert payload["dataset"]["sha256"] == "a" * 64
    assert payload["site_configuration"]["version"] == "3"
    assert payload["forecast"]["required_signals"]["tariff_per_kwh"] == "USD/kWh"
    assert payload["optimizer"]["settings"]["seed"] == 7
    assert payload["safety"]["device_write_authorized"] is False


def test_manifest_rejects_missing_provenance_or_ambiguous_contract():
    base = {
        "project_id": "p", "run_id": "r", "site_ref": "s",
        "created_at_utc": "2026-11-18T00:00:00Z",
        "dataset_sha256": "a" * 64, "dataset_schema_version": "1",
        "source_type": "synthetic", "site_configuration_version": "1",
        "site_configuration_sha256": "b" * 64,
        "required_signals": {"load_kw": "kW"}, "forecast_horizon_hours": 24,
        "optimizer_id": "opt", "optimizer_version": "1",
        "optimizer_settings": {}, "scenario_assumptions": {},
    }
    for field, value, message in [
        ("dataset_sha256", "not-a-hash", "dataset_sha256"),
        ("site_configuration_sha256", "c" * 63, "site_configuration_sha256"),
        ("created_at_utc", "2026-11-18T00:00:00", "timezone"),
        ("source_type", "unknown", "source_type"),
        ("required_signals", {"load_kw": ""}, "explicit unit"),
    ]:
        supplied = dict(base)
        supplied[field] = value
        with pytest.raises(ValueError, match=message):
            create_run_manifest(**supplied)


def test_manifest_rejects_non_finite_settings_and_unknown_model_signals():
    with pytest.raises(ValueError, match="finite"):
        create_run_manifest(
            project_id="p", run_id="r", site_ref="s",
            created_at_utc="2026-11-18T00:00:00Z",
            dataset_sha256="a" * 64, dataset_schema_version="1",
            source_type="synthetic", site_configuration_version="1",
            site_configuration_sha256="b" * 64,
            required_signals={"load_kw": "kW"}, forecast_horizon_hours=24,
            optimizer_id="opt", optimizer_version="1",
            optimizer_settings={"bad": float("inf")}, scenario_assumptions={},
        )
    with pytest.raises(ValueError, match="only reference required"):
        create_run_manifest(
            project_id="p", run_id="r", site_ref="s",
            created_at_utc="2026-11-18T00:00:00Z",
            dataset_sha256="a" * 64, dataset_schema_version="1",
            source_type="synthetic", site_configuration_version="1",
            site_configuration_sha256="b" * 64,
            required_signals={"load_kw": "kW"}, forecast_horizon_hours=24,
            optimizer_id="opt", optimizer_version="1",
            optimizer_settings={}, scenario_assumptions={},
            forecast_model_ids={"wind_power_kw": "model"},
        )


def test_manifest_detects_tampering_and_cannot_authorize_commands():
    payload = _manifest().to_dict()
    changed = deepcopy(payload)
    changed["optimizer"]["settings"]["seed"] = 99
    assert verify_run_manifest(changed)["valid"] is False
    changed = deepcopy(payload)
    changed["safety"]["device_write_authorized"] = True
    assert verify_run_manifest(changed)["valid"] is False
    assert verify_run_manifest(payload)["valid"] is True


def test_manifest_return_value_is_detached_from_internal_state():
    manifest = _manifest()
    first = manifest.to_dict()
    first["optimizer"]["settings"]["seed"] = 999
    assert manifest.to_dict()["optimizer"]["settings"]["seed"] == 7



def test_a_run_id_is_stable_for_identical_run_defining_inputs():
    inputs = {
        "dataset_sha256": "a" * 64,
        "site_configuration_sha256": "b" * 64,
        "recommended_policy": "battery_first",
        "weights": {"cost": 0.7, "reliability": 0.3},
    }
    first = deterministic_run_id("run-demo", inputs)
    second = deterministic_run_id("run-demo", dict(inputs))
    assert first == second
    assert first.startswith("run-demo-")
    assert len(first) == len("run-demo-") + 16


def test_a_run_id_changes_when_a_run_defining_input_changes():
    base = {"dataset_sha256": "a" * 64, "recommended_policy": "battery_first"}
    changed = {"dataset_sha256": "a" * 64, "recommended_policy": "grid_first"}
    assert deterministic_run_id("run-demo", base) != deterministic_run_id("run-demo", changed)


def test_a_run_id_refuses_an_empty_prefix_or_payload():
    with pytest.raises(ValueError, match="prefix"):
        deterministic_run_id("   ", {"dataset_sha256": "a" * 64})
    with pytest.raises(ValueError, match="payload"):
        deterministic_run_id("run-demo", {})
