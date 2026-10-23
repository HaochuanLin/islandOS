"""Readiness gate for site-specific IslandOS scenarios.

This gate validates required inputs before a scenario is allowed to start. It does
not connect to sensors, execute dispatch, or certify engineering safety.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

DISPATCH_REQUIRED = {
    "site_name": "Site / microgrid name",
    "scenario_start": "Scenario start timestamp (ISO-8601 with timezone)",
    "telemetry.timestamp": "Latest telemetry timestamp (ISO-8601 with timezone)",
    "telemetry.source_reference": "Sensor ID, export filename, or source reference",
    "telemetry.wind_kw": "Current wind generation (kW)",
    "telemetry.pv_kw": "Current PV generation (kW)",
    "telemetry.critical_load_kw": "Current critical load (kW)",
    "telemetry.reservoir_level_m3": "Current usable freshwater inventory (m³)",
    "assets.reservoir_capacity_m3": "Usable reservoir capacity (m³)",
    "assets.ro_capacity_m3_per_hour": "RO production capacity (m³/h)",
    "assets.ro_specific_energy_kwh_per_m3": "RO electricity intensity (kWh/m³)",
}
CAPEX_REQUIRED = {
    "capex.ro_plant_rmb": "RO plant CAPEX (RMB)",
    "capex.reservoir_rmb": "Reservoir / water storage CAPEX (RMB)",
    "capex.integration_rmb": "Controls, electrical and integration CAPEX (RMB)",
    "capex.annual_om_rmb": "Estimated annual O&M cost (RMB/year)",
    "capex.source_reference": "Quote, estimate owner, date, or source reference",
}


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def _get(data, dotted):
    value = data
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def evaluate_readiness(payload: dict, mode: str = "dispatch", now=None, max_telemetry_age_minutes: int = 60) -> dict:
    """Return blockers and warnings. Missing critical inputs always block the requested mode."""
    if mode not in {"dispatch", "economic"}:
        raise ValueError("mode must be 'dispatch' or 'economic'")
    if (
        isinstance(max_telemetry_age_minutes, bool)
        or not isinstance(max_telemetry_age_minutes, int)
        or max_telemetry_age_minutes <= 0
    ):
        raise ValueError("max_telemetry_age_minutes must be a positive integer")
    if now is not None and not isinstance(now, datetime):
        raise ValueError("now must be a datetime when provided")
    if not isinstance(payload, dict):
        payload = {}
    blockers, warnings = [], []
    required = dict(DISPATCH_REQUIRED)
    if mode == "economic":
        required.update(CAPEX_REQUIRED)

    text_fields = {"site_name", "telemetry.source_reference"}
    if mode == "economic":
        text_fields.add("capex.source_reference")
    for path, label in required.items():
        value = _get(payload, path)
        if value is None or (isinstance(value, str) and not value.strip()):
            blockers.append({"code": "missing_required_input", "field": path, "message": f"Missing required input: {label}."})
        elif path in text_fields and not isinstance(value, str):
            blockers.append({"code": "invalid_text", "field": path, "message": f"{path} must be a non-empty text value."})

    # Check timestamps separately so invalid values do not crash the report.
    for path in ("scenario_start", "telemetry.timestamp"):
        value = _get(payload, path)
        if value is not None and value != "":
            try:
                _parse_time(value)
            except (ValueError, TypeError):
                blockers.append({"code": "invalid_timestamp", "field": path, "message": f"{path} must be ISO-8601 with a timezone offset."})

    telemetry_time = _get(payload, "telemetry.timestamp")
    if telemetry_time:
        try:
            t = _parse_time(telemetry_time)
            reference = now or datetime.now(timezone.utc)
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            age = (reference.astimezone(timezone.utc) - t.astimezone(timezone.utc)).total_seconds() / 60
            if age < -5:
                blockers.append({"code": "telemetry_from_future", "field": "telemetry.timestamp", "message": "Telemetry timestamp is more than 5 minutes in the future; check clock and timezone."})
            elif age > max_telemetry_age_minutes:
                blockers.append({"code": "stale_telemetry", "field": "telemetry.timestamp", "message": f"Telemetry is {age:.1f} minutes old; maximum allowed is {max_telemetry_age_minutes} minutes."})
        except (ValueError, TypeError):
            pass

    numeric_fields = (
        "telemetry.wind_kw", "telemetry.pv_kw", "telemetry.critical_load_kw",
        "telemetry.reservoir_level_m3", "assets.reservoir_capacity_m3",
        "assets.ro_capacity_m3_per_hour", "assets.ro_specific_energy_kwh_per_m3",
    )
    numeric = {}
    for path in numeric_fields:
        value = _get(payload, path)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            blockers.append({"code": "invalid_number", "field": path, "message": f"{path} must be numeric, not boolean."})
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            blockers.append({"code": "invalid_number", "field": path, "message": f"{path} must be numeric."})
            continue
        if not math.isfinite(number) or number < 0:
            blockers.append({"code": "invalid_number", "field": path, "message": f"{path} must be finite and non-negative."})
            continue
        numeric[path] = number

    level = numeric.get("telemetry.reservoir_level_m3")
    capacity = numeric.get("assets.reservoir_capacity_m3")
    if level is not None and capacity is not None and level > capacity:
        blockers.append({"code": "reservoir_level_exceeds_capacity", "field": "telemetry.reservoir_level_m3", "message": "Reported usable water inventory exceeds reservoir capacity."})
    if numeric.get("assets.ro_capacity_m3_per_hour") == 0:
        blockers.append({"code": "zero_ro_capacity", "field": "assets.ro_capacity_m3_per_hour", "message": "RO capacity must be greater than zero for an RO scenario."})
    if numeric.get("assets.ro_specific_energy_kwh_per_m3") == 0:
        blockers.append({"code": "zero_ro_energy_intensity", "field": "assets.ro_specific_energy_kwh_per_m3", "message": "RO electricity intensity must be greater than zero."})

    if mode == "economic":
        for path, label in CAPEX_REQUIRED.items():
            if path.endswith("source_reference"):
                continue
            value = _get(payload, path)
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                blockers.append({"code": "invalid_number", "field": path, "message": f"{label} must be numeric, not boolean."})
                continue
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                blockers.append({"code": "invalid_number", "field": path, "message": f"{label} must be numeric."})
                continue
            if not math.isfinite(number) or number < 0:
                blockers.append({"code": "invalid_number", "field": path, "message": f"{label} must be finite and non-negative."})
        if not blockers and all((_get(payload, p) is not None) for p in CAPEX_REQUIRED):
            warnings.append({"code": "capex_is_user_supplied", "message": "CAPEX/O&M are staff-entered estimates; the gate does not verify quotations, taxes, financing, or lifecycle assumptions."})

    # Sensor connection is deliberately not implied by the presence of telemetry fields.
    source_type = _get(payload, "telemetry.source_type")
    if source_type not in {"sensor_export", "measured", "manual"}:
        warnings.append({"code": "telemetry_provenance_unconfirmed", "message": "Telemetry source_type should be sensor_export, measured, or manual; values are not independently authenticated."})
    if mode == "dispatch":
        warnings.append({"code": "economics_not_evaluated", "message": "Dispatch readiness does not establish financial viability. Use --mode economic for a CAPEX/O&M completeness gate."})

    return {
        "schema_version": "1.0",
        "mode": mode,
        "status": "BLOCKED" if blockers else "READY_FOR_OFFLINE_SCENARIO",
        "can_start": not blockers,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
        "scope_note": "Input-completeness gate only. READY does not mean field-safe, sensor-authenticated, or approved for live control. This tool never starts dispatch.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", help="Staff-prepared site readiness JSON")
    parser.add_argument("--mode", choices=("dispatch", "economic"), default="dispatch")
    parser.add_argument("--max-telemetry-age-minutes", type=int, default=60)
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    args = parser.parse_args()
    if args.max_telemetry_age_minutes <= 0:
        parser.error("--max-telemetry-age-minutes must be positive")
    try:
        payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read valid JSON input: {exc}")
    report = evaluate_readiness(payload, args.mode, max_telemetry_age_minutes=args.max_telemetry_age_minutes)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Readiness: {report['status']} | mode={args.mode} | blockers={report['blocker_count']} | warnings={report['warning_count']}")
        for item in report["blockers"] + report["warnings"]:
            print(f"- [{item['code']}] {item['message']}")
    raise SystemExit(0 if report["can_start"] else 2)


if __name__ == "__main__":
    main()
