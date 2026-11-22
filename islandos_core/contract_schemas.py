"""A machine-readable description of the three application-facing contracts.

`app_view_models` declares the field names; this module adds, for each field, what it
carries (unit), whether it can be `null`, and which layer owns it (site / page / run /
contract). The names are taken from the same constants the builders assert, so a drifted
builder fails the schema test rather than silently producing a schema that describes a
shape nobody emits.

Generated file: `docs/contracts/app_view_models.v2.json` (checked by
`tests/test_contract_schemas.py`; regenerate with `python -m islandos_core.contract_schemas`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .app_view_models import (
    ANNUAL_BASIS_FIELDS,
    ANNUAL_PROJECTION_FIELDS,
    CONTRACT_VERSION,
    HISTORY_FIELDS,
    PAGE_CUSTOMER_DASHBOARD,
    PAGE_JOINT_OPTIMIZER,
    PAGE_SETTING_KEYS,
    REQUEST_FIELDS,
    RESULT_SUMMARY_FIELDS,
    RUN_REQUEST_SITE_FIELDS,
    RUN_SETTING_KEYS,
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "contracts" / "app_view_models.v2.json"

# name -> (type, unit, nullable, owner)
_REQUEST = {
    "schema_version": ("integer", "-", False, "contract"),
    "request_type": ("string", "-", False, "contract"),
    "page": ("string", "-", False, "page"),
    "site": ("object", "kW / kWh / currency-per-kWh / SOC fraction", False, "site"),
    "history": ("object", "kW per signal, ISO-8601 timestamps", False, "data"),
    "page_settings": ("object", "per page", False, "page"),
    "run_settings": ("object", "per page", False, "run"),
    "request_sha256": ("string", "-", False, "contract"),
}
_SITE = {
    "pv_rated_kw": ("number", "kW", False, "site"),
    "wind_rated_kw": ("number", "kW", False, "site"),
    "grid_import_limit_kw": ("number", "kW", False, "site"),
    "battery_capacity_kwh": ("number", "kWh", False, "site"),
    "battery_power_kw": ("number", "kW", False, "site"),
    "battery_initial_soc": ("number", "fraction", False, "site"),
    "battery_min_soc": ("number", "fraction", False, "site"),
    "battery_max_soc": ("number", "fraction", False, "site"),
    "diesel_rated_kw": ("number", "kW", False, "site"),
    "diesel_variable_cost_per_kwh": ("number", "currency/kWh", False, "site"),
    "digest": ("string", "-", False, "site"),
}
_HISTORY = {
    "timestamps_utc": ("array[string]", "ISO-8601", False, "data"),
    "signals": ("object[number[]]", "kW or currency/kWh per signal", False, "data"),
    "units": ("object[string]", "-", False, "data"),
    "hour_count": ("integer", "hours", False, "data"),
    "provenance": ("string", "-", False, "data"),
    "source_sha256": ("string", "-", True, "data"),
}
_RESULT = {
    "schema_version": ("integer", "-", False, "contract"),
    "record_type": ("string", "-", False, "contract"),
    "page": ("string", "-", False, "page"),
    "recommended_policy": ("string", "-", True, "run"),
    "recommended_policy_label": ("string", "-", False, "display"),
    "estimated_24h_energy_cost": ("number", "currency/24h", True, "run"),
    "unmet_load_kwh": ("number", "kWh/24h", True, "run"),
    "grid_first_estimated_24h_energy_cost": ("number", "currency/24h", True, "run"),
    "service_equivalent": ("boolean", "-", True, "run"),
    "cost_comparison_valid": ("boolean", "-", True, "run"),
    "cost_reduction_vs_grid_first": ("number", "currency/24h", True, "run"),
    "savings_claim_withheld": ("boolean", "-", False, "gate"),
    "candidate_policies": ("array[string]", "-", False, "run"),
    "run_id": ("string", "-", True, "run"),
    "manifest_sha256": ("string", "-", True, "run"),
    "evidence_sha256": ("string", "-", True, "run"),
    "decision_record_status": ("string", "-", True, "run"),
    "physical_audit_passed": ("boolean", "-", True, "run"),
    "scenarios_audited": ("array[string]", "-", True, "run"),
    "currency": ("string", "-", True, "display"),
    "summary_sha256": ("string", "-", False, "contract"),
}
_ANNUAL = {
    "schema_version": ("integer", "-", False, "contract"),
    "record_type": ("string", "-", False, "contract"),
    "run_id": ("string", "-", False, "run"),
    "manifest_sha256": ("string", "-", False, "run"),
    "data_provenance": ("string", "-", False, "provenance"),
    "summary_source": ("string", "-", False, "provenance"),
    "currency": ("string", "-", True, "display"),
    "basis": ("object", "days / hours / flags", False, "run"),
    "figures": ("object[number]", "kWh / currency / hours", False, "run"),
    "components_inside_annual_energy_cost": ("object[number]", "currency", False, "run"),
    "definitions": ("object[object]", "-", False, "contract"),
    "scope": ("string", "-", False, "contract"),
    "projection_sha256": ("string", "-", False, "contract"),
}
_ANNUAL_BASIS = {
    "days_equivalent_per_year": ("integer", "days", False, "assumption"),
    "hours_equivalent_per_year": ("integer", "hours", False, "assumption"),
    "equal_day_assumption": ("string", "-", False, "assumption"),
    "derived_from_run": ("boolean", "-", False, "provenance"),
    "site_validated": ("boolean", "-", False, "provenance"),
    "measured": ("boolean", "-", False, "provenance"),
    "bill": ("boolean", "-", False, "provenance"),
}


def _fields(spec_map: dict, names) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "type": spec_map[name][0],
            "unit": spec_map[name][1],
            "nullable": spec_map[name][2],
            "owner": spec_map[name][3],
        }
        for name in names
    ]


def contract_schema() -> dict[str, Any]:
    """The three contracts plus the nested blocks a client must read."""
    return {
        "contract_version": CONTRACT_VERSION,
        "request_type": "islandos_run_request",
        "contracts": {
            "run_request": {
                "fields": _fields(_REQUEST, REQUEST_FIELDS),
                "nested": {
                    "site": _fields(_SITE, RUN_REQUEST_SITE_FIELDS),
                    "history": _fields(_HISTORY, HISTORY_FIELDS),
                },
                "page_settings_keys": {
                    page: list(keys) for page, keys in PAGE_SETTING_KEYS.items()
                },
                "run_settings_keys": {
                    page: list(keys) for page, keys in RUN_SETTING_KEYS.items()
                },
            },
            "run_result_summary": {"fields": _fields(_RESULT, RESULT_SUMMARY_FIELDS)},
            "annual_projection": {
                "fields": _fields(_ANNUAL, ANNUAL_PROJECTION_FIELDS),
                "nested": {"basis": _fields(_ANNUAL_BASIS, ANNUAL_BASIS_FIELDS)},
            },
        },
        "pages": [PAGE_CUSTOMER_DASHBOARD, PAGE_JOINT_OPTIMIZER],
    }


def write_schema(path: Path | None = None) -> Path:
    target = path or SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(contract_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


if __name__ == "__main__":
    print(write_schema())
