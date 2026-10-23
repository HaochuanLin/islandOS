"""Validate hourly IslandOS CSV inputs without silently repairing data.

Expected columns:
timestamp,wind_kw,pv_kw,critical_load_kw,water_demand_m3,cooling_demand_kw_th

Timestamps must be ISO-8601 and numeric values must be finite and non-negative.
The validator reports issues; it never fills, clips, or interpolates values.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = (
    "timestamp",
    "wind_kw",
    "pv_kw",
    "critical_load_kw",
    "water_demand_m3",
    "cooling_demand_kw_th",
)
NUMERIC_COLUMNS = REQUIRED_COLUMNS[1:]
SOURCE_TYPES = ("measured", "public", "synthetic", "forecast")


def _parse_timestamp(value: str):
    value = value.strip()
    if not value:
        raise ValueError("empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone offset (for example +00:00 or Z)")
    return parsed


def validate_csv(path, source_type: str, expected_interval_minutes: int = 60) -> dict:
    """Return a deterministic quality report for a CSV time series."""
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of: {', '.join(SOURCE_TYPES)}")
    if (
        isinstance(expected_interval_minutes, bool)
        or not isinstance(expected_interval_minutes, int)
        or expected_interval_minutes <= 0
    ):
        raise ValueError("expected_interval_minutes must be a positive integer")

    issues = []
    parsed_rows = []
    row_count = 0
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing_columns = [column for column in REQUIRED_COLUMNS if column not in headers]
        duplicate_columns = sorted({column for column in headers if headers.count(column) > 1})
        if duplicate_columns:
            issues.append({"code": "duplicate_columns", "columns": duplicate_columns})
        if missing_columns:
            return {
                "file": Path(path).name,
                "source_type": source_type,
                "status": "invalid",
                "row_count": 0,
                "issues": [{"code": "missing_columns", "columns": missing_columns}],
                "summary": {},
            }
        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            timestamp = None
            try:
                timestamp = _parse_timestamp(row.get("timestamp") or "")
            except ValueError as exc:
                issues.append({"code": "invalid_timestamp", "line": line_number, "detail": str(exc)})
            values = {}
            for column in NUMERIC_COLUMNS:
                raw = row.get(column)
                if raw is None or not raw.strip():
                    issues.append({"code": "missing_value", "line": line_number, "column": column})
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    issues.append({"code": "non_numeric", "line": line_number, "column": column})
                    continue
                if not math.isfinite(value):
                    issues.append({"code": "non_finite", "line": line_number, "column": column})
                    continue
                if value < 0:
                    issues.append({"code": "negative_value", "line": line_number, "column": column, "value": value})
                    continue
                values[column] = value
            if timestamp is not None:
                parsed_rows.append((line_number, timestamp, values))

    if row_count == 0:
        issues.append({"code": "empty_dataset"})

    seen = {}
    previous = None
    expected_delta = None
    for line_number, timestamp, _ in parsed_rows:
        if timestamp in seen:
            issues.append({"code": "duplicate_timestamp", "line": line_number, "first_line": seen[timestamp]})
        else:
            seen[timestamp] = line_number
        if previous is not None:
            delta = (timestamp - previous[1]).total_seconds() / 60
            if delta <= 0:
                issues.append({"code": "non_monotonic_timestamp", "line": line_number})
            elif delta != expected_interval_minutes:
                issues.append({
                    "code": "interval_mismatch",
                    "line": line_number,
                    "actual_minutes": delta,
                    "expected_minutes": expected_interval_minutes,
                })
        previous = (line_number, timestamp)

    codes = sorted({issue["code"] for issue in issues})
    return {
        "file": Path(path).name,
        "source_type": source_type,
        "status": "valid" if not issues and row_count > 0 else "invalid",
        "row_count": row_count,
        "columns_checked": list(REQUIRED_COLUMNS),
        "expected_interval_minutes": expected_interval_minutes,
        "issue_count": len(issues),
        "issue_codes": codes,
        "issues": issues,
        "summary": {
            "timestamped_rows": len(parsed_rows),
            "numeric_columns": list(NUMERIC_COLUMNS),
            "data_was_modified": False,
            "note": "No imputation, clipping, interpolation, or unit conversion was performed.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument("--source-type", required=True, choices=SOURCE_TYPES)
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_csv(args.csv_path, args.source_type, args.interval_minutes)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"File: {report['file']} | source: {report['source_type']} | status: {report['status']}")
        print(f"Rows: {report['row_count']} | issues: {report.get('issue_count', len(report['issues']))}")
        for issue in report["issues"]:
            print(f"- {issue}")
    raise SystemExit(0 if report["status"] == "valid" else 1)


if __name__ == "__main__":
    main()
