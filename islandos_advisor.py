"""End-to-end recommendation-only dispatch advisor for recorded telemetry."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys

from islandos_io import (
    apply_device_mapping,
    build_dispatch_input_rows,
    load_device_mapping,
    validate_telemetry,
)
from experiments.rolling_horizon_dispatch import parse_scenario_csv, simulate_rolling


POLICIES = ("rolling", "ro_first", "ice_first", "perfect_information")
OPERATIONAL_POLICIES = ("rolling", "ro_first", "ice_first")
WEIGHT_PROFILES = {
    "balanced": {"unmet_water": 0.45, "unmet_cooling": 0.45, "remaining_surplus": 0.10},
    "water_priority": {"unmet_water": 0.60, "unmet_cooling": 0.30, "remaining_surplus": 0.10},
    "cooling_priority": {"unmet_water": 0.30, "unmet_cooling": 0.60, "remaining_surplus": 0.10},
    "energy_efficiency": {"unmet_water": 0.40, "unmet_cooling": 0.40, "remaining_surplus": 0.20},
}


def _read_rows(path, input_format):
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    chosen = input_format
    if chosen == "auto":
        chosen = "csv" if path.lower().endswith(".csv") else "jsonl"
    if chosen == "csv":
        yield from csv.DictReader(text.splitlines())
        return
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            yield {"__parse_error__": "line %d: %s" % (line_number, exc)}
            continue
        if not isinstance(row, dict):
            yield {"__parse_error__": "line %d: JSONL rows must be objects" % line_number}
            continue
        yield row


def _score(result, scenario, weights=None):
    weights = weights or WEIGHT_PROFILES["balanced"]
    water_total = max(sum(scenario.water_demand_m3_per_hour), 1e-9)
    cooling_total = max(sum(scenario.cooling_demand_kw_th), 1e-9)
    power_total = max(sum(scenario.available_surplus_kw), 1e-9)
    return (
        weights["unmet_water"] * result["water_unmet_m3"] / water_total
        + weights["unmet_cooling"] * result["cooling_unmet_kwh_th"] / cooling_total
        + weights["remaining_surplus"] * result["remaining_surplus_kwh"] / power_total
    )


def evaluate_dispatch_rows(dispatch_rows, name="telemetry"):
    """Run the shared policy comparison used by the CLI and web UI."""
    if not dispatch_rows:
        raise ValueError("at least one dispatch input row is required")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(dispatch_rows[0].keys()))
    writer.writeheader()
    writer.writerows(dispatch_rows)
    parsed = parse_scenario_csv(buffer.getvalue(), name=name)
    results = {}
    for policy in POLICIES:
        results[policy] = simulate_rolling(
            parsed["scenario"],
            parsed["forecast_surplus_kw"],
            policy,
            forecast_water_demand_m3_per_hour=parsed["forecast_water_demand_m3_per_hour"],
        )

    eligible = tuple(
        policy for policy in OPERATIONAL_POLICIES
        if results[policy]["constraint_violation_hours"] == 0
    )
    balanced_scores = {
        policy: round(_score(results[policy], parsed["scenario"], WEIGHT_PROFILES["balanced"]), 6)
        for policy in OPERATIONAL_POLICIES
    }
    recommended = min(eligible, key=lambda policy: (balanced_scores[policy], policy)) if eligible else None

    sensitivity = []
    for profile_name, profile_weights in WEIGHT_PROFILES.items():
        profile_scores = {
            policy: round(_score(results[policy], parsed["scenario"], profile_weights), 6)
            for policy in OPERATIONAL_POLICIES
        }
        sensitivity.append({
            "weight_profile": profile_name,
            "weights": profile_weights,
            "policy_scores": profile_scores,
            "winner_for_this_input": (
                min(eligible, key=lambda policy: (profile_scores[policy], policy))
                if eligible else None
            ),
        })
    winner_counts = {
        policy: sum(row["winner_for_this_input"] == policy for row in sensitivity)
        for policy in OPERATIONAL_POLICIES
    }
    comparison = []
    for policy in POLICIES:
        result = results[policy]
        comparison.append({
            "policy": policy,
            "normalized_score": round(_score(result, parsed["scenario"], WEIGHT_PROFILES["balanced"]), 6),
            "eligible_for_recommendation": policy in eligible,
            "water_unmet_m3": result["water_unmet_m3"],
            "cooling_unmet_kwh_th": result["cooling_unmet_kwh_th"],
            "remaining_surplus_kwh": result["remaining_surplus_kwh"],
            "constraint_violation_hours": result["constraint_violation_hours"],
            "final_water_inventory_m3": result["final_water_inventory_m3"],
            "final_cold_inventory_kwh_th": result["final_cold_inventory_kwh_th"],
        })
    return {
        "status": "advice_ready" if recommended is not None else "operator_review_required",
        "score_weights": WEIGHT_PROFILES["balanced"],
        "weight_sensitivity": sensitivity,
        "weight_sensitivity_winner_counts": winner_counts,
        "weight_sensitivity_interpretation": (
            "Winner counts are across the declared weight profiles for this input only; "
            "they are not statistical confidence or a guarantee of field performance."
        ),
        "policy_comparison": comparison,
        "eligible_policies": list(eligible),
        "recommended_policy_for_operator_review": recommended,
        "recommendation_reason": (
            "lowest declared normalized score among zero-constraint-violation operational policies for this input only"
            if recommended is not None else
            "no operational policy satisfies all reported constraints; operator review is required and no policy is recommended"
        ),
        "hourly_audit_by_policy": {policy: results[policy]["hourly_audit"] for policy in POLICIES},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Hourly telemetry CSV/JSONL file, or - for stdin")
    parser.add_argument("--format", choices=("auto", "csv", "jsonl"), default="auto")
    parser.add_argument("--source", default="recorded-telemetry")
    parser.add_argument("--mapping", help="Optional vendor field/unit mapping JSON")
    parser.add_argument("--max-age-seconds", type=float, default=300.0)
    parser.add_argument("--received-at", help="Timezone-aware ISO timestamp for deterministic replay")
    parser.add_argument("--output", default="-", help="JSON report path, or - for stdout")
    args = parser.parse_args(argv)

    try:
        received_at = None
        if args.received_at:
            value = args.received_at[:-1] + "+00:00" if args.received_at.endswith("Z") else args.received_at
            received_at = datetime.fromisoformat(value)
            if received_at.tzinfo is None or received_at.utcoffset() is None:
                raise ValueError("--received-at must include a timezone")
            received_at = received_at.astimezone(timezone.utc)
        if args.max_age_seconds < 0:
            raise ValueError("--max-age-seconds must be non-negative")
        mapping = load_device_mapping(args.mapping) if args.mapping else None
        records = []
        for index, row in enumerate(_read_rows(args.input, args.format), start=1):
            if "__parse_error__" in row:
                records.append({
                    "row": index, "valid": False, "errors": [row["__parse_error__"]],
                    "warnings": [], "values": {}, "timestamp_utc": None,
                })
                continue
            canonical = apply_device_mapping(row, mapping) if mapping else row
            frame = validate_telemetry(
                canonical, source=args.source, received_at=received_at,
                max_age_seconds=args.max_age_seconds,
            )
            record = frame.as_dict()
            record["row"] = index
            records.append(record)

        invalid = [record for record in records if not record["valid"]]
        if invalid:
            report = {
                "status": "rejected",
                "mode": "recorded_file_replay",
                "source": args.source,
                "valid_rows": len(records) - len(invalid),
                "rejected_rows": len(invalid),
                "telemetry_audit": records,
                "physical_write_performed": False,
                "operator_action_required": True,
            }
            _write_report(report, args.output)
            return 2

        dispatch_rows = build_dispatch_input_rows(records)
        evaluation = evaluate_dispatch_rows(dispatch_rows, name=Path(args.input).stem or "stdin")
        report = {
            "mode": "recorded_file_replay",
            "data_status": "user-supplied file; not site-validated",
            "source": args.source,
            "row_count": len(records),
            "forecast_method": "supplied forecasts where present; otherwise persistence baseline; first row cold-start seeded",
            **evaluation,
            "telemetry_audit": records,
            "operator_action_required": True,
            "physical_write_performed": False,
            "limitations": [
                "recorded-file replay, not a live sensor connection",
                "synthetic or supplied forecasts are not validated for a real island",
                "perfect_information is a hindsight reference, not an operational policy",
                "no PLC command, setpoint write, or actuator operation is performed",
            ],
        }
        _write_report(report, args.output)
        return 0
    except (OSError, ValueError, TypeError, csv.Error, json.JSONDecodeError) as exc:
        print("islandOS advisor error: %s" % exc, file=sys.stderr)
        return 2


def _write_report(report, output_path):
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if output_path == "-":
        sys.stdout.write(text + "\n")
    else:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
