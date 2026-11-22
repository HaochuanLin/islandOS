"""Annual operating figures, and the assumption that turns a 24-hour run into them.

`INTEGRATION.md` §6.4 fixes what the annual *investment* inputs mean; §6.5 records that
nothing bridged a run's simulated day to a year. This module is that bridge, written in
the only honest form available: the caller has to **declare** how many days a year
stands for, the record prints that declaration next to the numbers, and the record says
plainly that it is a projection of a run — not a utility bill, not measured annual
consumption, and not site-validated.

What it does not do: it never reads a customer's annual bill, never compares entered
bills against the projection, and never guesses a load shape. A year of a site is not
365 copies of one simulated day unless somebody states that it is.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

RECORD_TYPE = "annual_operating_basis_projection"

# Unit / period / meaning for every figure this record emits, so a page can label
# them without inventing wording of its own.
DEFINITIONS = {
    "annual_load_energy_kwh": (
        "kWh / year",
        "energy the site demanded over the projection year",
    ),
    "annual_load_served_kwh": (
        "kWh / year",
        "energy actually delivered to load over the projection year",
    ),
    "annual_unmet_load_kwh": (
        "kWh / year",
        "demanded energy not served, before and after the same assumption",
    ),
    "annual_energy_cost": (
        "currency / year (net)",
        "modelled net energy cost of the dispatch over the projection year, already net of "
        "export revenue; a projection, not a bill",
    ),
    "annual_equipment_operating_cost": (
        "currency / year",
        "fuel, battery throughput and diesel start/stop inside the annual energy cost above; a "
        "breakdown of that cost, never an addition to it",
    ),
    "annual_diesel_run_hours": (
        "hours / year",
        "hours the diesel generator was committed in the run, scaled by the same assumption",
    ),
}

_SCOPE = (
    "Annual projection of a 24-hour offline dispatch run under a declared equal-days "
    "assumption: not a utility bill, not measured annual consumption, not a site-validated "
    "forecast, and not an equipment command."
)

_SUMMARY_KEYS = (
    "load_energy_kwh",
    "load_served_kwh",
    "unmet_load_kwh",
    "estimated_energy_cost",
    "diesel_fuel_cost",
    "battery_degradation_cost",
    "diesel_start_cost",
    "diesel_stop_cost",
)


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def annualise_run_summary(
    summary: Mapping[str, Any],
    *,
    dispatch_rows: Sequence[Mapping[str, Any]] | None = None,
    simulated_hours: int,
    days_equivalent_per_year: int,
    run_id: str,
    manifest_sha256: str,
    data_provenance: str,
    summary_source: str,
) -> dict:
    """Project one run's day onto a year, carrying the assumption in the record.

    `summary_source` names which object inside the run the summary came from, because a
    run holds several (the recommended schedule's own dispatch, per-scenario replays,
    candidate summaries). The projection is only traceable if the reader can go back to
    the exact one.
    """
    if not isinstance(summary, Mapping):
        raise ValueError("summary must be the run's simulated summary mapping")
    for key in _SUMMARY_KEYS:
        if key not in summary:
            raise ValueError(f"summary is missing {key}")
    if isinstance(simulated_hours, bool) or not isinstance(simulated_hours, int) or simulated_hours < 1:
        raise ValueError("simulated_hours must be a positive integer")
    if isinstance(days_equivalent_per_year, bool) or not isinstance(days_equivalent_per_year, int):
        raise ValueError("days_equivalent_per_year must be an integer")
    if not 1 <= days_equivalent_per_year <= 366:
        raise ValueError("days_equivalent_per_year must be between 1 and 366")
    for name, value in (
        ("run_id", run_id),
        ("manifest_sha256", manifest_sha256),
        ("data_provenance", data_provenance),
        ("summary_source", summary_source),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")

    values = {key: _number(summary[key], key) for key in _SUMMARY_KEYS}
    diesel_run_hours = 0.0
    for row in dispatch_rows or ():
        if not isinstance(row, Mapping):
            raise ValueError("dispatch rows must be mappings")
        if _number(row.get("diesel_generation_kw", 0.0), "diesel_generation_kw") > 0:
            diesel_run_hours += 1.0

    days = float(days_equivalent_per_year)
    equipment_operating_cost = (
        values["diesel_fuel_cost"] + values["battery_degradation_cost"]
        + values["diesel_start_cost"] + values["diesel_stop_cost"]
    )
    record = {
        "schema_version": 1,
        "record_type": RECORD_TYPE,
        "run_id": run_id.strip(),
        "manifest_sha256": manifest_sha256.strip(),
        "data_provenance": data_provenance.strip(),
        "summary_source": summary_source.strip(),
        "simulated_hours": simulated_hours,
        "basis": {
            "days_equivalent_per_year": days_equivalent_per_year,
            "hours_equivalent_per_year": days_equivalent_per_year * simulated_hours,
            "equal_day_assumption": (
                "each simulated day stands for the annual average day; no seasonal weighting, "
                "no load-growth and no tariff-year change are applied"
            ),
            "derived_from_run": True,
            "site_validated": False,
            "measured": False,
            "bill": False,
        },
        "figures": {
            "annual_load_energy_kwh": round(values["load_energy_kwh"] * days, 6),
            "annual_load_served_kwh": round(values["load_served_kwh"] * days, 6),
            "annual_unmet_load_kwh": round(values["unmet_load_kwh"] * days, 6),
            "annual_energy_cost": round(values["estimated_energy_cost"] * days, 6),
            "annual_equipment_operating_cost": round(equipment_operating_cost * days, 6),
            "annual_diesel_run_hours": round(diesel_run_hours * days, 6),
        },
        "components_inside_annual_energy_cost": {
            "diesel_fuel_cost": round(values["diesel_fuel_cost"] * days, 6),
            "battery_degradation_cost": round(values["battery_degradation_cost"] * days, 6),
            "diesel_start_stop_cost": round(
                (values["diesel_start_cost"] + values["diesel_stop_cost"]) * days, 6
            ),
        },
        "definitions": {
            key: {"unit": unit, "meaning": meaning}
            for key, (unit, meaning) in DEFINITIONS.items()
        },
        "scope": _SCOPE,
        "device_write_authorized": False,
        "command_generated": False,
    }
    record["annualisation_sha256"] = _sha256(_canonical(record))
    return record


def verify_annual_operating_basis(record: Mapping[str, Any]) -> dict:
    """Fail-closed checks for an annual projection that a report or a page may quote."""
    errors: list[str] = []
    if not isinstance(record, Mapping) or record.get("record_type") != RECORD_TYPE:
        return {"valid": False, "errors": ["record is not an annual operating basis projection"]}
    digest = record.get("annualisation_sha256")
    payload = {key: value for key, value in record.items() if key != "annualisation_sha256"}
    if not isinstance(digest, str) or len(digest) != 64:
        errors.append("annualisation_sha256 must be a 64-character digest")
    else:
        try:
            if _sha256(_canonical(payload)) != digest:
                errors.append("annualisation_sha256 does not match the record contents")
        except (TypeError, ValueError) as exc:
            errors.append(f"record contents are not canonical JSON: {exc}")
    basis = record.get("basis")
    if not isinstance(basis, Mapping):
        errors.append("record is missing its basis block")
    else:
        if basis.get("derived_from_run") is not True:
            errors.append("an annual projection must say it is derived from the run")
        if basis.get("site_validated") is not False:
            errors.append("an annual projection must never claim site validation")
        if basis.get("bill") is not False:
            errors.append("an annual projection must never claim to be a utility bill")
        days = basis.get("days_equivalent_per_year")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 366:
            errors.append("basis.days_equivalent_per_year must be an integer between 1 and 366")
    source = record.get("summary_source")
    if not isinstance(source, str) or not source.strip():
        errors.append("an annual projection must name the summary it projected")
    figures = record.get("figures")
    if not isinstance(figures, Mapping):
        errors.append("record is missing its figures block")
    else:
        for key in DEFINITIONS:
            if key not in figures:
                errors.append(f"figures is missing {key}")
    if record.get("device_write_authorized") is not False:
        errors.append("an annual projection must never authorize a device write")
    if record.get("command_generated") is not False:
        errors.append("an annual projection must never claim a generated command")
    return {"valid": not errors, "errors": errors}
