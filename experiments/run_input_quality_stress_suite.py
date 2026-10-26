"""Deterministic malformed-input stress suite for IslandOS CSV boundaries.

This suite verifies parser rejection behavior using synthetic fixtures. It does
not test site measurement quality, forecast accuracy, or physical safety.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Callable

from experiments.rolling_horizon_dispatch import (
    generate_synthetic_scenario_csv,
    parse_scenario_csv,
)


def _rewrite_csv(
    text: str,
    transform: Callable[[dict[str, str], int], None] | None = None,
    *,
    remove_columns: tuple[str, ...] = (),
    header_only: bool = False,
) -> str:
    reader = csv.DictReader(io.StringIO(text))
    fields = [name for name in (reader.fieldnames or []) if name not in remove_columns]
    rows = list(reader)
    if transform is not None:
        for index, row in enumerate(rows):
            transform(row, index)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    if not header_only:
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    return output.getvalue()


def build_input_quality_cases(hours: int = 4) -> list[dict[str, Any]]:
    """Return a baseline plus deterministic invalid CSV fixtures."""
    if isinstance(hours, bool) or not isinstance(hours, int) or not 2 <= hours <= 168:
        raise ValueError("hours must be an integer from 2 to 168")
    base = generate_synthetic_scenario_csv(hours)
    rows = list(csv.DictReader(io.StringIO(base)))

    def changed(row_index: int, column: str, value: str) -> str:
        return _rewrite_csv(
            base,
            lambda row, index: row.__setitem__(column, value) if index == row_index else None,
        )

    cases: list[dict[str, Any]] = [{
        "name": "valid_synthetic_baseline",
        "expected_rejected": False,
        "description": "Valid generated CSV should parse successfully.",
        "csv": base,
    }]
    lines = base.splitlines()
    duplicate_header = lines[0].replace("forecast_surplus_kw", "actual_surplus_kw", 1) + "\\n" + "\\n".join(lines[1:]) + "\\n"
    extra_field_lines = list(lines)
    extra_field_lines[1] += ",unexpected"
    short_row_lines = list(lines)
    short_row_lines[1] = ",".join(short_row_lines[1].split(",")[:-1])
    invalid = [
        ("duplicate_header", "Duplicate column names must be rejected.", duplicate_header),
        ("extra_row_field", "A row with more fields than the header must be rejected.", "\\n".join(extra_field_lines) + "\\n"),
        ("short_row", "A row with fewer fields than the header must be rejected.", "\\n".join(short_row_lines) + "\\n"),
        ("empty_input", "Empty text must be rejected.", ""),
        ("header_only", "A header without data rows must be rejected.", base.splitlines()[0] + "\n"),
        ("missing_required_column", "Missing required cooling column must be rejected.",
         _rewrite_csv(base, remove_columns=("cooling_demand_kw_th",))),
        ("blank_timestamp", "Blank timestamp must be rejected.", changed(0, "timestamp_utc", "")),
        ("malformed_timestamp", "Malformed timestamp must be rejected.", changed(0, "timestamp_utc", "not-a-timestamp")),
        ("timezone_naive_timestamp", "Timestamp without timezone must be rejected.",
         changed(0, "timestamp_utc", rows[0]["timestamp_utc"].replace("Z", ""))),
        ("duplicate_timestamp", "Duplicate timestamp must be rejected.",
         _rewrite_csv(base, lambda row, index: row.__setitem__("timestamp_utc", rows[0]["timestamp_utc"]) if index == 1 else None)),
        ("non_monotonic_timestamp", "Out-of-order timestamp must be rejected.",
         _rewrite_csv(base, lambda row, index: row.__setitem__("timestamp_utc", "2025-12-31T23:00:00Z") if index == 1 else None)),
        ("hour_gap", "A two-hour gap in an hourly series must be rejected.",
         _rewrite_csv(base, lambda row, index: row.__setitem__("timestamp_utc", "2026-01-01T02:00:00Z") if index == 1 else None)),
        ("nan_actual_surplus", "NaN actual surplus must be rejected.", changed(0, "actual_surplus_kw", "nan")),
        ("infinite_forecast_surplus", "Infinite forecast surplus must be rejected.", changed(0, "forecast_surplus_kw", "inf")),
        ("negative_water_demand", "Negative water demand must be rejected.", changed(0, "water_demand_m3", "-1")),
        ("nonnumeric_cooling_demand", "Nonnumeric cooling demand must be rejected.", changed(0, "cooling_demand_kw_th", "lots")),
        ("blank_forecast_water_demand", "Blank optional forecast-water value must be rejected when the column is present.",
         changed(0, "forecast_water_demand_m3", "")),
    ]
    for name, description, csv_text in invalid:
        cases.append({
            "name": name,
            "expected_rejected": True,
            "description": description,
            "csv": csv_text,
        })
    return cases


def run_input_quality_stress_suite(hours: int = 4) -> dict[str, Any]:
    """Exercise CSV parser acceptance/rejection and hash every exact fixture."""
    if isinstance(hours, bool) or not isinstance(hours, int) or not 2 <= hours <= 168:
        raise ValueError("hours must be an integer from 2 to 168")
    results = []
    for case in build_input_quality_cases(hours):
        csv_text = case["csv"]
        error = None
        accepted = False
        try:
            parsed = parse_scenario_csv(csv_text, name=case["name"])
            accepted = True
            parsed_rows = len(parsed["timestamps_utc"])
        except (ValueError, TypeError, KeyError) as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            parsed_rows = 0
        expected_rejected = case["expected_rejected"]
        results.append({
            "name": case["name"],
            "description": case["description"],
            "expected_rejected": expected_rejected,
            "actual_rejected": not accepted,
            "expectation_met": (not accepted) == expected_rejected,
            "parsed_rows": parsed_rows,
            "error": error,
            "input_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        })

    report: dict[str, Any] = {
        "report_version": 1,
        "suite": "deterministic_csv_input_quality_stress",
        "status": "synthetic_parser_boundary_test_not_site_validation",
        "hours_per_valid_fixture": hours,
        "case_count": len(results),
        "passed_cases": sum(item["expectation_met"] for item in results),
        "failed_cases": sum(not item["expectation_met"] for item in results),
        "all_expectations_met": all(item["expectation_met"] for item in results),
        "all_fixtures_simulation_only": True,
        "physical_write_performed": False,
        "live_control_enabled": False,
        "results": results,
        "interpretation": [
            "Fixtures are designed malformed inputs derived from a synthetic CSV, not measured telemetry.",
            "A parser rejection proves only that the tested input condition was rejected.",
            "A valid synthetic baseline does not establish site-data quality or source authenticity.",
            "This suite does not replace sensor validation, physical interlocks, or independent safety review.",
        ],
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=4, help="valid baseline length, 2–168 hours")
    parser.add_argument("--output", type=Path, default=Path("build/input-quality-stress/report.json"))
    args = parser.parse_args(argv)
    try:
        report = run_input_quality_stress_suite(args.hours)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Input quality suite: {report['passed_cases']}/{report['case_count']} expectations met.")
    print(f"Report SHA-256: {report['report_sha256']}")
    print(f"Report: {args.output}")
    print("SYNTHETIC PARSER TEST ONLY — no physical equipment commands were issued.")
    return 0 if report["all_expectations_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
