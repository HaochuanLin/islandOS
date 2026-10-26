"""Fail-closed autonomous flexible-load gate for simulation only.

Consumes a rolling-dispatch audit row and emits a bounded simulated ON/OFF/HOLD
decision with reason codes. It never writes to a PLC, actuator, or live plant.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REQUIRED_NUMERIC = (
    "actual_surplus_kw",
    "ro_power_kw",
    "ice_power_kw",
    "water_inventory_m3",
)
REQUIRED_BOOLEANS = (
    "telemetry_valid",
    "interlocks_healthy",
    "operator_stop",
)


def _number(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{key} must be finite and non-negative")
    return result


def evaluate_simulated_action(
    plan_row: dict[str, Any],
    *,
    telemetry_valid: bool,
    interlocks_healthy: bool,
    operator_stop: bool = False,
    max_total_power_kw: float = 500.0,
    minimum_water_inventory_m3: float = 20.0,
) -> dict[str, Any]:
    """Apply independent, fail-closed gates to one simulated dispatch row.

    The policy only authorizes a simulated action inside the configured envelope.
    Thresholds are illustrative defaults, not site-approved engineering limits.
    """
    if not isinstance(plan_row, dict):
        raise ValueError("plan_row must be a JSON object")
    flags = {
        "telemetry_valid": telemetry_valid,
        "interlocks_healthy": interlocks_healthy,
        "operator_stop": operator_stop,
    }
    for key, value in flags.items():
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be boolean")

    # Validate configuration before considering any action.
    max_power = _number({"value": max_total_power_kw}, "value")
    min_water = _number({"value": minimum_water_inventory_m3}, "value")
    if max_power <= 0:
        raise ValueError("max_total_power_kw must be greater than zero")

    # Fail closed before reading telemetry values: malformed/missing data cannot
    # accidentally produce an ON decision when the quality gate is false.
    if not telemetry_valid:
        return _result("HOLD", "HOLD_TELEMETRY_INVALID", plan_row, flags, None, None)
    if not interlocks_healthy:
        return _result("HOLD", "HOLD_INTERLOCK_UNHEALTHY", plan_row, flags, None, None)
    if operator_stop:
        return _result("HOLD", "HOLD_OPERATOR_STOP", plan_row, flags, None, None)

    values = {key: _number(plan_row, key) for key in REQUIRED_NUMERIC}
    total_power = values["ro_power_kw"] + values["ice_power_kw"]
    if total_power > max_power:
        return _result("HOLD", "HOLD_AUTHORIZED_POWER_LIMIT", plan_row, flags, total_power, max_power)
    if total_power > values["actual_surplus_kw"] + 1e-6:
        return _result("HOLD", "HOLD_SURPLUS_BALANCE_FAILED", plan_row, flags, total_power, max_power)
    if int(plan_row.get("total_constraint_violations", 0)) != 0:
        return _result("HOLD", "HOLD_DISPATCH_CONSTRAINT_VIOLATION", plan_row, flags, total_power, max_power)

    # Do not start RO when inventory already exceeds the lower safety buffer
    # threshold? The threshold here is a low-inventory guard: below it, an
    # existing rolling plan may run if power is available; otherwise OFF.
    ro_requested = plan_row.get("ro_active")
    if not isinstance(ro_requested, bool):
        raise ValueError("ro_active must be boolean")
    if ro_requested and values["water_inventory_m3"] < min_water:
        return _result("HOLD", "HOLD_WATER_INVENTORY_BELOW_MINIMUM", plan_row, flags, total_power, max_power)

    action = "ON" if ro_requested else "OFF"
    reason = "SIM_RO_PLAN_ON_APPROVED" if ro_requested else "SIM_RO_PLAN_OFF_APPROVED"
    return _result(action, reason, plan_row, flags, total_power, max_power)


def _result(action, reason, row, flags, total_power, max_power):
    return {
        "action": action,
        "reason_code": reason,
        "evidence": {
            **flags,
            "hour_index": row.get("hour_index"),
            "actual_surplus_kw": row.get("actual_surplus_kw"),
            "total_requested_power_kw": total_power,
            "configured_max_total_power_kw": max_power,
        },
        "mode": "simulation_only",
        "physical_write_performed": False,
        "live_control_enabled": False,
        "requires_site_validation_before_deployment": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", help="JSON object with plan_row and gate flags")
    parser.add_argument("--output", default="-", help="Output JSON path, or - for stdout")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = evaluate_simulated_action(
        payload.get("plan_row"),
        telemetry_valid=payload.get("telemetry_valid"),
        interlocks_healthy=payload.get("interlocks_healthy"),
        operator_stop=payload.get("operator_stop", False),
        max_total_power_kw=payload.get("max_total_power_kw", 500.0),
        minimum_water_inventory_m3=payload.get("minimum_water_inventory_m3", 20.0),
    )
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output == "-":
        print(text, end="")
    else:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
