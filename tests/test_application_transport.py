"""The schema file and the read-only transport agree with the builders they describe."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from islandos_core.app_view_models import (
    ANNUAL_BASIS_FIELDS,
    ANNUAL_PROJECTION_FIELDS,
    CONTRACT_VERSION,
    HISTORY_FIELDS,
    REQUEST_FIELDS,
    RESULT_SUMMARY_FIELDS,
    RUN_REQUEST_SITE_FIELDS,
    build_run_request,
)
from islandos_core.contract_schemas import SCHEMA_PATH, contract_schema, write_schema
from islandos_core.site_inputs import SiteAssumptions
from islandos_core.transport import create_server

REPO_ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 11, 1, tzinfo=timezone.utc)
TIMESTAMPS = tuple(START + timedelta(hours=index) for index in range(96))
HISTORY = {
    "pv_power": [max(0.0, 5.0 + 3.0 * ((i % 24) / 24)) for i in range(96)],
    "wind_power": [3.0 + (i % 5) * 0.2 for i in range(96)],
    "essential_load": [8.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
    "electricity_price": [0.08 if i % 24 < 6 else 0.20 for i in range(96)],
}
UNITS = {
    "pv_power": "kW", "wind_power": "kW", "essential_load": "kW",
    "electricity_price": "USD/kWh",
}


def _site() -> SiteAssumptions:
    return SiteAssumptions(
        pv_rated_kw=10.0, wind_rated_kw=8.0, grid_import_limit_kw=20.0,
        battery_capacity_kwh=20.0, battery_power_kw=5.0,
        battery_initial_soc=0.60, battery_min_soc=0.10, battery_max_soc=0.95,
        diesel_rated_kw=0.0, diesel_variable_cost_per_kwh=0.0,
    )


def _dashboard_request():
    return build_run_request(
        page="customer_dashboard", site=_site(), timestamps=TIMESTAMPS,
        history=HISTORY, units=UNITS,
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


def test_the_schema_names_every_field_the_builders_emit():
    schema = contract_schema()
    assert schema["contract_version"] == CONTRACT_VERSION
    assert [field["name"] for field in schema["contracts"]["run_request"]["fields"]] == list(REQUEST_FIELDS)
    assert [field["name"] for field in schema["contracts"]["run_request"]["nested"]["site"]] == list(
        RUN_REQUEST_SITE_FIELDS
    )
    assert [field["name"] for field in schema["contracts"]["run_request"]["nested"]["history"]] == list(
        HISTORY_FIELDS
    )
    assert [field["name"] for field in schema["contracts"]["run_result_summary"]["fields"]] == list(
        RESULT_SUMMARY_FIELDS
    )
    annual = schema["contracts"]["annual_projection"]
    assert [field["name"] for field in annual["fields"]] == list(ANNUAL_PROJECTION_FIELDS)
    assert [field["name"] for field in annual["nested"]["basis"]] == list(ANNUAL_BASIS_FIELDS)


def test_every_field_states_unit_nullability_and_owner():
    schema = contract_schema()
    blocks = [schema["contracts"]["run_request"]["fields"], schema["contracts"]["run_request"]["nested"]["site"],
              schema["contracts"]["run_request"]["nested"]["history"]]
    blocks.append(schema["contracts"]["run_result_summary"]["fields"])
    blocks.append(schema["contracts"]["annual_projection"]["fields"])
    blocks.append(schema["contracts"]["annual_projection"]["nested"]["basis"])
    for block in blocks:
        for field in block:
            assert field["unit"], field
            assert isinstance(field["nullable"], bool), field
            assert field["owner"] in {
                "contract", "page", "run", "site", "data", "display", "gate", "provenance", "assumption",
            }, field


def test_the_committed_schema_file_matches_the_module():
    assert SCHEMA_PATH.exists(), "run python -m islandos_core.contract_schemas"
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == contract_schema()
    regenerated = write_schema()
    assert json.loads(regenerated.read_text(encoding="utf-8")) == committed


def test_the_transport_serves_the_schema_and_runs_a_request():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base}/contracts", timeout=10) as response:
            assert response.status == 200
            assert json.loads(response.read())["contract_version"] == CONTRACT_VERSION

        request = _dashboard_request()
        body = json.dumps(request).encode("utf-8")
        http_request = Request(
            f"{base}/run", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(http_request, timeout=60) as response:
            assert response.status == 200
            payload = json.loads(response.read())
        assert payload["page"] == "customer_dashboard"
        assert payload["annual"] is None
        assert payload["result"]["recommended_policy_label"]
        assert set(payload["result"]) == set(RESULT_SUMMARY_FIELDS)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_the_transport_replays_a_joint_optimizer_request():
    optimizer_history = {
        "pv_power_kw": HISTORY["pv_power"], "wind_power_kw": HISTORY["wind_power"],
        "load_kw": HISTORY["essential_load"], "tariff_per_kwh": HISTORY["electricity_price"],
    }
    optimizer_units = {
        "pv_power_kw": "kW", "wind_power_kw": "kW", "load_kw": "kW", "tariff_per_kwh": "USD/kWh",
    }
    site = SiteAssumptions(
        pv_rated_kw=10.0, wind_rated_kw=8.0, grid_import_limit_kw=20.0,
        battery_capacity_kwh=20.0, battery_power_kw=5.0,
        battery_initial_soc=0.60, battery_min_soc=0.10, battery_max_soc=0.95,
        diesel_rated_kw=10.0, diesel_variable_cost_per_kwh=0.30,
    )
    request = build_run_request(
        page="joint_resource_optimizer", site=site, timestamps=TIMESTAMPS,
        history=optimizer_history, units=optimizer_units, page_settings={},
        run_settings={
            "currency": "USD",
            "optimizer_settings": {"population_size": 4, "generations": 1, "seed": 31},
            "availability": {"grid_all_hours": True, "diesel_all_hours": True},
        },
        provenance="Synthetic demonstration data", source_sha256=None,
    )
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        http_request = Request(
            f"{base}/run", data=json.dumps(request).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(http_request, timeout=60) as response:
            assert response.status == 200
            payload = json.loads(response.read())
        assert payload["page"] == "joint_resource_optimizer"
        assert payload["annual"] is None
        assert payload["result"]["run_id"].startswith("run-")
        assert payload["result"]["decision_record_status"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_only_the_schema_is_cross_origin_readable():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base}/contracts", timeout=10) as response:
            assert response.headers["Access-Control-Allow-Origin"] == "*"
        with urlopen(f"{base}/health", timeout=10) as response:
            assert response.headers["Access-Control-Allow-Origin"] is None
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_the_transport_refuses_an_invalid_request_with_400():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        request = _dashboard_request()
        request["page"] = "unknown_page"
        http_request = Request(
            f"{base}/run", data=json.dumps(request).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urlopen(http_request, timeout=10)
        except HTTPError as exc:
            assert exc.code == 400
            assert "page must be one of" in json.loads(exc.read())["error"]
        else:  # pragma: no cover - the request above must fail
            raise AssertionError("an unknown page was accepted")

        with urlopen(f"{base}/contracts", timeout=10) as response:
            assert response.status == 200
        try:
            urlopen(f"{base}/nope", timeout=10)
        except HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)
