"""A machine-readable description of the application-facing contracts.

`app_view_models` declares the field names; this module adds, for each field, what it
carries (unit), whether it can be `null`, and which layer owns it (site / page / run /
contract). The names are taken from the same constants the builders assert, so a drifted
builder fails the schema test rather than silently producing a schema that describes a
shape nobody emits.

Generated file: `docs/contracts/app_view_models.v3.json` (checked by
`tests/test_application_transport.py`; regenerate with
`python -m islandos_core.contract_schemas`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .app_view_models import (
    ANNUAL_BASIS_FIELDS,
    ANNUAL_PROJECTION_FIELDS,
    CONTRACT_VERSION,
    DEVICE_SUMMARY_FIELDS,
    DEVICE_TASK_FIELDS,
    HISTORY_FIELDS,
    PAGE_CUSTOMER_DASHBOARD,
    PAGE_DEVICE_PLANNER,
    PAGE_INPUTS_FIELDS,
    PAGE_JOINT_OPTIMIZER,
    PAGE_SETTING_KEYS,
    REQUEST_FIELDS,
    RESULT_SUMMARY_FIELDS,
    RUN_REQUEST_SITE_FIELDS,
    RUN_SETTING_KEYS,
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "contracts" / "app_view_models.v3.json"

# name -> (type, unit, nullable, owner)
_REQUEST = {
    "schema_version": ("integer", "-", False, "contract"),
    "request_type": ("string", "-", False, "contract"),
    "page": ("string", "-", False, "page"),
    "site": ("object", "kW / kWh / currency-per-kWh / SOC fraction", False, "site"),
    "history": ("object", "kW per signal, ISO-8601 timestamps", False, "data"),
    "page_settings": ("object", "per page", False, "page"),
    "page_inputs": ("object", "per page; null when the page has only numeric knobs", True, "page"),
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
_PAGE_INPUTS = {
    "task_power_budget_kw": ("array[number]", "kW", False, "page"),
    "tasks": ("array[object]", "kW / kWh / steps", False, "page"),
}
_DEVICE_TASK = {
    "task_id": ("string", "-", False, "page"),
    "name": ("string", "-", False, "page"),
    "load_class": ("string", "critical / semi_flexible / fully_flexible", False, "page"),
    "rated_power_kw": ("number", "kW", False, "page"),
    "required_energy_kwh": ("number", "kWh", False, "page"),
    "earliest_start_step": ("integer", "step (hour)", False, "page"),
    "latest_finish_step": ("integer", "step (hour)", False, "page"),
    "min_power_kw": ("number", "kW", False, "page"),
    "minimum_run_steps": ("integer", "step (hour)", False, "page"),
    "interruptible": ("boolean", "-", False, "page"),
    "priority": ("integer", "order", False, "page"),
    "availability": ("array[boolean]", "-", True, "page"),
    "critical_power_profile_kw": ("array[number]", "kW", True, "page"),
}
_DEVICE_SUMMARY = {
    "schema_version": ("integer", "-", False, "contract"),
    "record_type": ("string", "-", False, "contract"),
    "page": ("string", "-", False, "page"),
    "run_id": ("string", "-", True, "run"),
    "method": ("string", "-", False, "run"),
    "critical_energy_kwh": ("number", "kWh/24h", False, "run"),
    "flexible_task_energy_kwh": ("number", "kWh/24h", False, "run"),
    "scheduled_energy_charge": ("number", "currency/24h", False, "run"),
    "peak_task_demand_kw": ("number", "kW", False, "run"),
    "grid_import_kwh": ("number", "kWh/24h", False, "run"),
    "reference_grid_import_kwh": ("number", "kWh/24h", False, "run"),
    "estimated_energy_cost": ("number", "currency/24h", False, "run"),
    "reference_estimated_energy_cost": ("number", "currency/24h", False, "run"),
    "critical_unmet_load_kwh": ("number", "kWh/24h", False, "run"),
    "flexible_load_shed_kwh": ("number", "kWh/24h", False, "run"),
    "currency": ("string", "-", True, "display"),
    "summary_sha256": ("string", "-", False, "contract"),
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
                    "page_inputs": _fields(_PAGE_INPUTS, PAGE_INPUTS_FIELDS),
                    "device_tasks": _fields(_DEVICE_TASK, DEVICE_TASK_FIELDS),
                },
                "page_settings_keys": {
                    page: list(keys) for page, keys in PAGE_SETTING_KEYS.items()
                },
                "run_settings_keys": {
                    page: list(keys) for page, keys in RUN_SETTING_KEYS.items()
                },
            },
            "run_result_summary": {"fields": _fields(_RESULT, RESULT_SUMMARY_FIELDS)},
            "device_flexibility_summary": {
                "fields": _fields(_DEVICE_SUMMARY, DEVICE_SUMMARY_FIELDS)
            },
            "annual_projection": {
                "fields": _fields(_ANNUAL, ANNUAL_PROJECTION_FIELDS),
                "nested": {"basis": _fields(_ANNUAL_BASIS, ANNUAL_BASIS_FIELDS)},
            },
        },
        "pages": [PAGE_CUSTOMER_DASHBOARD, PAGE_JOINT_OPTIMIZER, PAGE_DEVICE_PLANNER],
    }


def write_schema(path: Path | None = None) -> Path:
    target = path or SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(contract_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


TS_PATH = Path(__file__).resolve().parents[1] / "frontend" / "src" / "contracts.ts"

_TS_TYPES = {
    "integer": "number",
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "object": "Record<string, unknown>",
    "array[string]": "string[]",
    "array[number]": "number[]",
    "array[boolean]": "boolean[]",
    "array[object]": "Record<string, unknown>[]",
    "object[number]": "Record<string, number>",
    "object[number[]]": "Record<string, number[]>",
    "object[string]": "Record<string, string>",
    "object[object]": "Record<string, Record<string, unknown>>",
}

# Nested blocks that deserve a named interface instead of an opaque record. The keys are
# (contract, nested block); the field override is (contract, field) -> interface name.
_TS_NESTED = {
    ("run_request", "site"): "RunRequestSite",
    ("run_request", "history"): "RunRequestHistory",
    ("run_request", "page_inputs"): "RunRequestPageInputs",
    ("run_request", "device_tasks"): "DeviceTask",
    ("annual_projection", "basis"): "AnnualProjectionBasis",
}
_TS_FIELD_INTERFACE = {
    ("run_request", "site"): "RunRequestSite",
    ("run_request", "history"): "RunRequestHistory",
    ("run_request", "page_inputs"): "RunRequestPageInputs",
    ("annual_projection", "basis"): "AnnualProjectionBasis",
}
_TS_FIELD_ARRAY_INTERFACE = {
    ("run_request", "page_inputs", "tasks"): "DeviceTask",
}


def _ts_name(contract: str) -> str:
    return "".join(part.capitalize() for part in contract.split("_"))


def _ts_property(field: dict[str, Any], *, contract: str, block: str | None) -> tuple[str, str]:
    key = (contract, block, field["name"]) if block else (contract, field["name"])
    nested = _TS_FIELD_INTERFACE.get((contract, field["name"])) if block is None else None
    array_nested = _TS_FIELD_ARRAY_INTERFACE.get(key)
    if nested:
        base = nested
    elif array_nested:
        base = f"{array_nested}[]"
    else:
        base = _TS_TYPES[field["type"]]
    if field["nullable"]:
        base = f"{base} | null"
    name = field["name"]
    return name, base


def _ts_interface(
    name: str, fields: list[dict[str, Any]], *, contract: str, block: str | None,
) -> list[str]:
    lines = [f"export interface {name} {{"]
    for field in fields:
        prop, ts_type = _ts_property(field, contract=contract, block=block)
        unit = field["unit"].replace("*/", "")
        lines.append(f"  /** {field['type']} · {unit} · owner: {field['owner']} */")
        lines.append(f"  {prop}: {ts_type};")
    lines.append("}")
    return lines


def typescript_source() -> str:
    """TypeScript interfaces generated from the contract, for the static viewer's build.

    The names and types come from `contract_schema()`, so a drifted schema fails the byte
    comparison in `tests/test_application_transport.py` instead of leaving the front end
    typing a shape nobody emits.
    """
    schema = contract_schema()
    lines = [
        "// Generated by `python -m islandos_core.contract_schemas --typescript`.",
        "// Field names, types, units and owners come from `contract_schema()`; do not edit.",
        "",
    ]
    for contract, body in schema["contracts"].items():
        nested = body.get("nested") or {}
        for block, fields in nested.items():
            name = _TS_NESTED[(contract, block)]
            lines.extend(_ts_interface(name, fields, contract=contract, block=block))
            lines.append("")
    for contract, body in schema["contracts"].items():
        lines.extend(_ts_interface(
            _ts_name(contract), body["fields"], contract=contract, block=None,
        ))
        lines.append("")

    lines.append("export interface ContractField {")
    lines.append("  name: string;")
    lines.append("  type: string;")
    lines.append("  unit: string;")
    lines.append("  nullable: boolean;")
    lines.append("  owner: string;")
    lines.append("}")
    lines.append("")
    lines.append("export interface ContractBody {")
    lines.append("  fields: ContractField[];")
    lines.append("  nested?: Record<string, ContractField[]>;")
    lines.append("  page_settings_keys?: Record<string, string[]>;")
    lines.append("  run_settings_keys?: Record<string, string[]>;")
    lines.append("}")
    lines.append("")
    lines.append("export interface ContractSchema {")
    lines.append("  contract_version: number;")
    lines.append("  request_type: string;")
    lines.append("  contracts: {")
    for contract in schema["contracts"]:
        lines.append(f"    {contract}: ContractBody;")
    lines.append("  };")
    lines.append("  pages: string[];")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_typescript(path: Path | None = None) -> Path:
    target = path or TS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(typescript_source(), encoding="utf-8")
    return target


JSON_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "contracts"
    / f"app_view_models.v{CONTRACT_VERSION}.schema.json"
)

_JSON_SCALARS = {
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "string": {"type": "string"},
    "boolean": {"type": "boolean"},
}


def _json_value(field: dict[str, Any], *, ref: str | None = None, item_ref: str | None = None) -> dict:
    """One field's JSON Schema type, nullable included as a union with null."""
    base_type = field["type"]
    if ref:
        schema: dict[str, Any] = {"$ref": f"#/$defs/{ref}"}
    elif item_ref:
        schema = {"type": "array", "items": {"$ref": f"#/$defs/{item_ref}"}}
    elif base_type in _JSON_SCALARS:
        schema = dict(_JSON_SCALARS[base_type])
    elif base_type == "object":
        schema = {"type": "object"}
    elif base_type == "array[string]":
        schema = {"type": "array", "items": {"type": "string"}}
    elif base_type == "array[number]":
        schema = {"type": "array", "items": {"type": "number"}}
    elif base_type == "array[boolean]":
        schema = {"type": "array", "items": {"type": "boolean"}}
    elif base_type == "array[object]":
        schema = {"type": "array", "items": {"type": "object"}}
    elif base_type == "object[number]":
        schema = {"type": "object", "additionalProperties": {"type": "number"}}
    elif base_type == "object[number[]]":
        schema = {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "number"}},
        }
    elif base_type == "object[string]":
        schema = {"type": "object", "additionalProperties": {"type": "string"}}
    elif base_type == "object[object]":
        schema = {"type": "object", "additionalProperties": {"type": "object"}}
    else:
        raise KeyError(f"no JSON Schema mapping for contract type {base_type!r}")
    if field["nullable"]:
        return {"anyOf": [schema, {"type": "null"}]}
    return schema


def _json_object(
    fields: list[dict[str, Any]],
    *,
    refs: dict[str, tuple[str | None, str | None]] | None = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for field in fields:
        ref, item_ref = (refs or {}).get(field["name"], (None, None))
        props[field["name"]] = _json_value(field, ref=ref, item_ref=item_ref)
    if "schema_version" in props:
        # A report written under an older contract is a different document, not a value
        # that happens to be off by one: pin the version so a v2 file fails loudly.
        props["schema_version"] = {"type": "integer", "const": CONTRACT_VERSION}
    return {
        "type": "object",
        "properties": props,
        "required": [field["name"] for field in fields],
        "additionalProperties": False,
    }


def json_schema() -> dict[str, Any]:
    """The same contract, as a draft 2020-12 JSON Schema a standard validator can enforce.

    The long-form file (`app_view_models.v3.json`) describes type, unit, nullability and
    owner for a human reader; this one is the machine-checkable half. Objects here are
    closed (`additionalProperties: false`) because the builders assert the exact key set,
    and the per-page shape of `page_settings` / `run_settings` / `page_inputs` is encoded
    as `if`/`then` on `page` instead of being merged into one permissive object.
    """
    schema = contract_schema()
    contracts = schema["contracts"]

    defs: dict[str, Any] = {
        "run_request_site": _json_object(
            contracts["run_request"]["nested"]["site"]
        ),
        "run_request_history": _json_object(
            contracts["run_request"]["nested"]["history"]
        ),
        "device_task": _json_object(contracts["run_request"]["nested"]["device_tasks"]),
        "run_request_page_inputs": _json_object(
            contracts["run_request"]["nested"]["page_inputs"],
            refs={"tasks": (None, "device_task")},
        ),
        "run_result_summary": _json_object(contracts["run_result_summary"]["fields"]),
        "device_flexibility_summary": _json_object(
            contracts["device_flexibility_summary"]["fields"]
        ),
        "annual_projection_basis": _json_object(
            contracts["annual_projection"]["nested"]["basis"]
        ),
        "annual_projection": _json_object(
            contracts["annual_projection"]["fields"],
            refs={"basis": ("annual_projection_basis", None)},
        ),
    }

    page_conditions: list[dict[str, Any]] = []
    for page in schema["pages"]:
        page_keys = contracts["run_request"]["page_settings_keys"][page]
        run_keys = contracts["run_request"]["run_settings_keys"][page]
        then: dict[str, Any] = {
            "properties": {
                "page_settings": {
                    "type": "object",
                    "properties": {key: {} for key in page_keys},
                    "required": list(page_keys),
                    "additionalProperties": False,
                },
                "run_settings": {
                    "type": "object",
                    "properties": {key: {} for key in run_keys},
                    "required": list(run_keys),
                    "additionalProperties": False,
                },
            },
            "required": ["page_settings", "run_settings"],
        }
        if page == PAGE_DEVICE_PLANNER:
            then["required"].append("page_inputs")
            then["properties"]["page_inputs"] = {"$ref": "#/$defs/run_request_page_inputs"}
        else:
            then["properties"]["page_inputs"] = {"type": "null"}
        page_conditions.append(
            {
                "if": {"properties": {"page": {"const": page}}, "required": ["page"]},
                "then": then,
            }
        )

    request_schema = _json_object(
        contracts["run_request"]["fields"],
        refs={
            "site": ("run_request_site", None),
            "history": ("run_request_history", None),
        },
    )
    request_schema["allOf"] = page_conditions
    defs["run_request"] = request_schema

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://islandos.local/contracts/"
            f"app_view_models.v{CONTRACT_VERSION}.schema.json"
        ),
        "title": f"IslandOS application view models, contract version {CONTRACT_VERSION}",
        "description": (
            "Generated from islandos_core.contract_schemas; do not edit. "
            "Run: python -m islandos_core.contract_schemas --json-schema"
        ),
        "$defs": defs,
        "oneOf": [
            {"$ref": "#/$defs/run_request"},
            {"$ref": "#/$defs/run_result_summary"},
            {"$ref": "#/$defs/device_flexibility_summary"},
            {"$ref": "#/$defs/annual_projection"},
        ],
    }


def write_json_schema(path: Path | None = None) -> Path:
    target = path or JSON_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate the contract artifacts")
    parser.add_argument("--typescript", action="store_true", help="write frontend/src/contracts.ts")
    parser.add_argument("--json-schema", action="store_true", help="write the draft 2020-12 schema")
    args = parser.parse_args()
    if args.typescript:
        print(write_typescript())
    elif args.json_schema:
        print(write_json_schema())
    else:
        print(write_schema())
