from __future__ import annotations

from datetime import datetime, timezone

import pytest

from islandos_core.run_identity import (
    derive_input_group_id,
    derive_run_id,
    run_record_identity_fields,
)
from islandos_core.workspace_store import (
    RunRecordConflict,
    create_project,
    get_run_record,
    initialize_workspace,
    record_run_record,
    verify_audit_chain,
)


NOW = datetime(2026, 11, 26, 4, 0, tzinfo=timezone.utc)
FULL_REQUEST_SHA256 = "a" * 64


def _identity():
    timestamps = [
        datetime(2026, 1, 1, hour, tzinfo=timezone.utc)
        for hour in range(3)
    ]
    group = derive_input_group_id(
        timestamps=timestamps,
        signals={
            "pv_power_kw": [0.0, 1.5, 4.25],
            "wind_power_kw": [2.0, 2.5, 3.0],
            "load_kw": [10.0, 12.5, 11.0],
            "tariff_per_kwh": [0.20, 0.25, 0.30],
        },
        units={
            "pv_power_kw": "kW",
            "wind_power_kw": "kW",
            "load_kw": "kW",
            "tariff_per_kwh": "USD/kWh",
        },
    )
    return derive_run_id(
        page="customer_dashboard",
        input_group=group,
        site_configuration_sha256="2" * 64,
        page_settings={"demand_scale": 1.0},
        page_inputs={},
        run_settings={"currency": "USD"},
        forecast_settings={"horizon_hours": 24},
        model_selection_policy={"id": "forecast_policy_default", "version": "1"},
        model_catalogue_version="catalogue-v1",
        optimizer={"id": "customer_dashboard_policy_comparison", "version": "1"},
        algorithm_versions={"customer_workflow": "1"},
    )


def _workspace(tmp_path):
    db = tmp_path / "workspace.sqlite3"
    initialize_workspace(db, workspace_id="workspace-01", actor_id="tester", created_at=NOW)
    create_project(
        db, project_id="site-01", display_name="Site 01",
        actor_id="tester", consent_to_store_metadata=True, created_at=NOW,
    )
    return db


def test_run_identity_maps_to_immutable_record_and_replays(tmp_path):
    db = _workspace(tmp_path)
    identity = _identity()
    fields = run_record_identity_fields(identity)
    result = {"grid_cost": 12.5}

    record = record_run_record(
        db, project_id="site-01", **fields,
        request_sha256=FULL_REQUEST_SHA256,
        request_metadata={"history_rows": 3},
        result=result,
        actor_id="tester",
        consent_to_store_result=True,
        created_at=NOW,
    )
    assert record["run_id"] == identity.run_id
    assert record["page"] == "customer_dashboard"
    assert record["run_request_sha256"] == identity.run_identity_sha256
    assert record["input_group_id"] == identity.input_group.input_group_id
    assert record["identity_schema_version"] == 1
    assert record["record_schema_version"] == "1.1"
    assert record["idempotent_replay"] is False

    before = verify_audit_chain(db)["event_count"]
    replay = record_run_record(
        db, project_id="site-01", **fields,
        request_sha256=FULL_REQUEST_SHA256,
        request_metadata={"history_rows": 3},
        result=result,
        actor_id="tester",
        consent_to_store_result=True,
        created_at=NOW,
    )
    assert replay["idempotent_replay"] is True
    assert replay["created_at"] == record["created_at"]
    assert verify_audit_chain(db)["event_count"] == before

    with pytest.raises(RunRecordConflict) as conflict:
        record_run_record(
            db, project_id="site-01", **fields,
            request_sha256=FULL_REQUEST_SHA256,
            request_metadata={"history_rows": 3},
            result={"grid_cost": 13.0},
            actor_id="tester",
            consent_to_store_result=True,
            created_at=NOW,
        )
    assert conflict.value.code == "run_result_conflict"
    assert get_run_record(db, project_id="site-01", run_id=identity.run_id)["result"] == result
