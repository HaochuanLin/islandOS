"""The contract also exists as a draft 2020-12 JSON Schema a standard validator can enforce."""

from datetime import datetime, timedelta, timezone
import copy
import json

import jsonschema
import pytest

from islandos_core.app_view_models import (
    ANNUAL_BASIS_FIELDS,
    ANNUAL_PROJECTION_FIELDS,
    DEVICE_SUMMARY_FIELDS,
    PAGE_CUSTOMER_DASHBOARD,
    PAGE_DEVICE_PLANNER,
    RUN_REQUEST_SITE_FIELDS,
    build_run_request,
    RESULT_SUMMARY_FIELDS,
    REQUEST_FIELDS,
)
from islandos_core.contract_schemas import JSON_SCHEMA_PATH, json_schema
from islandos_core.flexible_tasks import DeviceTask
from islandos_core.run_orchestration import device_task_payload, replay_run_request
from islandos_core.site_inputs import SiteAssumptions, device_planner_demo_site

START = datetime(2026, 11, 1, tzinfo=timezone.utc)
TIMESTAMPS = tuple(START + timedelta(hours=index) for index in range(96))
SITE = SiteAssumptions(
    pv_rated_kw=10.0, wind_rated_kw=8.0, grid_import_limit_kw=20.0,
    battery_capacity_kwh=20.0, battery_power_kw=5.0,
    battery_initial_soc=0.60, battery_min_soc=0.10, battery_max_soc=0.95,
    diesel_rated_kw=0.0, diesel_variable_cost_per_kwh=0.0,
)
# The joint optimizer refuses to schedule without a diesel asset, so it gets its own site.
JOINT_SITE = SiteAssumptions(
    pv_rated_kw=10.0, wind_rated_kw=8.0, grid_import_limit_kw=20.0,
    battery_capacity_kwh=20.0, battery_power_kw=5.0,
    battery_initial_soc=0.60, battery_min_soc=0.10, battery_max_soc=0.95,
    diesel_rated_kw=10.0, diesel_variable_cost_per_kwh=0.30,
)
HISTORY = {
    "pv_power_kw": [max(0.0, 5.0 + 3.0 * ((i % 24) / 24)) for i in range(96)],
    "wind_power_kw": [3.0 + (i % 5) * 0.2 for i in range(96)],
    "load_kw": [8.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
    "tariff_per_kwh": [0.08 if i % 24 < 6 else 0.20 for i in range(96)],
}
UNITS = {
    "pv_power_kw": "kW", "wind_power_kw": "kW", "load_kw": "kW", "tariff_per_kwh": "USD/kWh",
}
DASH_HISTORY = {
    "pv_power": HISTORY["pv_power_kw"],
    "wind_power": HISTORY["wind_power_kw"],
    "essential_load": HISTORY["load_kw"],
    "electricity_price": HISTORY["tariff_per_kwh"],
}
DASH_UNITS = {
    "pv_power": "kW", "wind_power": "kW", "essential_load": "kW",
    "electricity_price": "USD/kWh",
}


def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _dashboard_request():
    return build_run_request(
        page=PAGE_CUSTOMER_DASHBOARD, site=SITE, timestamps=TIMESTAMPS,
        history=DASH_HISTORY, units=DASH_UNITS,
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
        provenance="Synthetic demonstration data", source_sha256=None,
    )


def _joint_request():
    return build_run_request(
        page="joint_resource_optimizer", site=JOINT_SITE, timestamps=TIMESTAMPS,
        history=HISTORY, units=UNITS, page_settings={},
        run_settings={
            "currency": "USD",
            "optimizer_settings": {"population_size": 4, "generations": 1, "seed": 31},
            "availability": {"grid_all_hours": True, "diesel_all_hours": True},
        },
        provenance="Synthetic demonstration data", source_sha256=None,
    )


def _device_request():
    stamps = tuple(START + timedelta(hours=h) for h in range(24))
    prices = [0.09 if h < 6 else 0.25 if 17 <= h <= 21 else 0.16 for h in range(24)]
    tasks = [
        DeviceTask("clinic-critical", "Clinic essential circuits", "critical", 3.0, 72.0,
                   0, 24, interruptible=False, priority=0,
                   critical_power_profile_kw=tuple([3.0] * 24)),
        DeviceTask("water-pump", "Water transfer pumping", "fully_flexible", 2.0, 8.0,
                   0, 24, minimum_run_steps=1, interruptible=True, priority=20),
    ]
    return build_run_request(
        page=PAGE_DEVICE_PLANNER, site=device_planner_demo_site(), timestamps=stamps,
        history={
            "pv_generation_kw": [max(0.0, 12.0 * (1.0 - abs(h - 12) / 7.0)) for h in range(24)],
            "wind_generation_kw": [3.0 + 1.5 * ((h % 6) / 5.0) for h in range(24)],
            "load_kw": [8.0] * 24, "tariff_per_kwh": prices,
        },
        units={"pv_generation_kw": "kW", "wind_generation_kw": "kW", "load_kw": "kW",
               "tariff_per_kwh": "USD/kWh"},
        page_settings={}, run_settings={"currency": "USD"},
        page_inputs={"task_power_budget_kw": [10.0] * 24,
                     "tasks": [device_task_payload(task) for task in tasks]},
        provenance="Synthetic demonstration data", source_sha256=None,
    )


def test_the_committed_json_schema_matches_the_module():
    assert JSON_SCHEMA_PATH.read_text(encoding="utf-8") == json_schema_source()


def json_schema_source() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"


def test_the_schema_requires_every_declared_field():
    schema = json_schema()
    expected = {
        "run_request": REQUEST_FIELDS,
        "run_request_site": RUN_REQUEST_SITE_FIELDS,
        "run_result_summary": RESULT_SUMMARY_FIELDS,
        "device_flexibility_summary": DEVICE_SUMMARY_FIELDS,
        "annual_projection": ANNUAL_PROJECTION_FIELDS,
        "annual_projection_basis": ANNUAL_BASIS_FIELDS,
    }
    for name, names in expected.items():
        assert schema["$defs"][name]["required"] == list(names)


@pytest.mark.parametrize("builder", [_dashboard_request, _joint_request, _device_request])
def test_a_real_request_and_its_replay_result_validate(builder):
    validator = _validator()
    request = builder()
    validator.validate(request)
    payload = replay_run_request(request)
    validator.validate(payload["result"])


def test_the_objects_are_closed_and_the_page_shapes_are_enforced():
    validator = _validator()
    request = _dashboard_request()

    extra_key = copy.deepcopy(request)
    extra_key["site"]["unexpected_kw"] = 1.0
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(extra_key)

    no_page_inputs = copy.deepcopy(_device_request())
    no_page_inputs["page_inputs"] = None
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(no_page_inputs)

    dashboard_inputs = copy.deepcopy(request)
    dashboard_inputs["page_inputs"] = {"task_power_budget_kw": [], "tasks": []}
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(dashboard_inputs)

    wrong_settings = copy.deepcopy(_joint_request())
    wrong_settings["run_settings"].pop("availability")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(wrong_settings)

    summary = replay_run_request(request)["result"]
    summary.pop("summary_sha256")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(summary)
