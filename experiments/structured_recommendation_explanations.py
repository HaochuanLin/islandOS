"""Structured, deterministic reason codes for advisory dispatch recommendations.

This module explains a small, explicit rule set. It does not invoke an LLM,
operate equipment, or replace the existing dispatch engine.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REASON_TEMPLATES = {
    "HOLD_DATA_QUALITY_FAILED": (
        "HOLD: data quality check failed. Do not act on this recommendation until the input data has been reviewed."
    ),
    "HOLD_CONSTRAINT_CHECK_FAILED": (
        "HOLD: a required hard-constraint check failed. Operator review is required before any decision."
    ),
    "NO_START_WATER_BUFFER_SUFFICIENT": (
        "Do not start the RO load: the reported water inventory is at or above the configured target."
    ),
    "NO_START_INSUFFICIENT_SURPLUS": (
        "Do not start the RO load: available surplus power is below the configured required power."
    ),
    "START_SURPLUS_AVAILABLE_AND_WATER_BUFFER_LOW": (
        "Start is eligible for operator review: available surplus power meets the configured power threshold and water inventory is below the configured target."
    ),
}


def _finite_nonnegative(inputs: dict[str, Any], name: str) -> float:
    value = inputs.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a numeric finite non-negative value")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a numeric finite non-negative value")
    return number


def evaluate_recommendation(inputs: dict[str, Any]) -> dict[str, Any]:
    """Evaluate explicit advisory rules and return an auditable explanation."""
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be a JSON object")
    quality = inputs.get("telemetry_quality_passed")
    constraints = inputs.get("hard_constraints_passed")
    if not isinstance(quality, bool):
        raise ValueError("telemetry_quality_passed must be boolean")
    if not isinstance(constraints, bool):
        raise ValueError("hard_constraints_passed must be boolean")

    # Validate numeric fields even for HOLD decisions so malformed telemetry
    # cannot be silently ignored or accidentally used later.
    available = _finite_nonnegative(inputs, "available_surplus_kw")
    required = _finite_nonnegative(inputs, "required_power_kw")
    inventory = _finite_nonnegative(inputs, "water_inventory_m3")
    target = _finite_nonnegative(inputs, "target_water_inventory_m3")

    if not quality:
        code, recommendation = "HOLD_DATA_QUALITY_FAILED", "HOLD"
    elif not constraints:
        code, recommendation = "HOLD_CONSTRAINT_CHECK_FAILED", "HOLD"
    elif inventory >= target:
        code, recommendation = "NO_START_WATER_BUFFER_SUFFICIENT", "NO_START"
    elif available < required:
        code, recommendation = "NO_START_INSUFFICIENT_SURPLUS", "NO_START"
    else:
        code, recommendation = "START_SURPLUS_AVAILABLE_AND_WATER_BUFFER_LOW", "START_ELIGIBLE_FOR_OPERATOR_REVIEW"

    return {
        "recommendation": recommendation,
        "reason_code": code,
        "explanation_en": REASON_TEMPLATES[code],
        "evidence": {
            "telemetry_quality_passed": quality,
            "hard_constraints_passed": constraints,
            "available_surplus_kw": available,
            "required_power_kw": required,
            "water_inventory_m3": inventory,
            "target_water_inventory_m3": target,
        },
        "mode": "advisory_recommendation_only",
        "operator_action_required": True,
        "physical_write_performed": False,
        "not_a_deployed_control_system": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", nargs="?", help="JSON object containing the documented rule inputs")
    parser.add_argument("--output", default="-", help="JSON output path, or - for stdout")
    args = parser.parse_args(argv)
    sample = {
        "telemetry_quality_passed": True,
        "hard_constraints_passed": True,
        "available_surplus_kw": 250.0,
        "required_power_kw": 200.0,
        "water_inventory_m3": 120.0,
        "target_water_inventory_m3": 300.0,
    }
    try:
        inputs = json.loads(Path(args.input_json).read_text(encoding="utf-8")) if args.input_json else sample
        report = evaluate_recommendation(inputs)
        text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output == "-":
            print(text, end="")
        else:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
