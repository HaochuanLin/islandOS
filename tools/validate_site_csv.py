#!/usr/bin/env python3
"""Preflight an IslandOS hourly CSV for schema, values, timestamps, and interval gaps.

This validates file structure and consistency, not sensor authenticity or site accuracy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_energy_water_strategies import load_site_steps


def _validate_csv_shape(path: Path) -> None:
    """Reject duplicate headers and rows whose field count differs from the header."""
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header:
                raise ValueError("CSV is missing a header")
            if any(not column.strip() for column in header):
                raise ValueError("CSV header contains an empty column name")
            if len(header) != len(set(header)):
                raise ValueError("CSV contains duplicate column names")
            for row_number, row in enumerate(reader, start=2):
                if not row:
                    continue
                if len(row) > len(header):
                    raise ValueError(
                        f"Row {row_number}: contains {len(row) - len(header)} extra field(s) beyond the header"
                    )
                if len(row) < len(header):
                    raise ValueError(
                        f"Row {row_number}: missing {len(header) - len(row)} field(s) compared with the header"
                    )
    except csv.Error as exc:
        raise ValueError(f"CSV parse error: {exc}") from exc


def inspect_csv(path: Path, interval_minutes: int) -> dict:
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be >= 1")
    _validate_csv_shape(path)
    steps = load_site_steps(path)
    if not steps:
        raise ValueError("CSV must contain at least one data row")
    parsed: list[datetime] = []
    for index, step in enumerate(steps, start=2):
        try:
            # Python 3.10's fromisoformat does not consistently accept the
            # ISO-8601 UTC designator "Z"; normalize it to an explicit offset.
            raw_timestamp = step.timestamp.strip()
            if raw_timestamp.endswith("Z"):
                raw_timestamp = raw_timestamp[:-1] + "+00:00"
            stamp = datetime.fromisoformat(raw_timestamp)
        except ValueError as exc:
            raise ValueError(f"Row {index}: timestamp must be ISO-8601, got {step.timestamp!r}") from exc
        parsed.append(stamp)

    aware = [stamp.utcoffset() is not None for stamp in parsed]
    if any(aware) and not all(aware):
        raise ValueError("timestamps mix timezone-aware and timezone-naive values")
    expected_seconds = interval_minutes * 60
    intervals = [(b - a).total_seconds() for a, b in zip(parsed, parsed[1:])]
    bad = [
        {"from": steps[i].timestamp, "to": steps[i + 1].timestamp, "seconds": delta}
        for i, delta in enumerate(intervals) if delta != expected_seconds
    ]
    return {
        "valid": not bad,
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "row_count": len(steps),
        "required_interval_minutes": interval_minutes,
        "timezone_mode": "offset-aware" if all(aware) else "naive/local",
        "first_timestamp": steps[0].timestamp,
        "last_timestamp": steps[-1].timestamp,
        "interval_count": len(intervals),
        "irregular_intervals": bad[:50],
        "irregular_interval_count": len(bad),
        "warnings": [
            "This report checks schema and consistency only; it cannot authenticate sensor provenance.",
            "Naive timestamps require a separately documented site timezone.",
            "A valid file is not proof of measured data, forecast accuracy, or operational safety.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="input site CSV")
    parser.add_argument("--interval-minutes", type=int, default=60,
                        help="expected interval in minutes (default: 60)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="emit a machine-readable report")
    args = parser.parse_args(argv)
    try:
        report = inspect_csv(args.csv, args.interval_minutes)
    except (OSError, ValueError) as exc:
        report = {"valid": False, "file": args.csv.name, "error": str(exc)}
        if args.json_output:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"INVALID: {args.csv}: {exc}", file=sys.stderr)
        return 2

    if args.json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report["valid"]:
        print(f"VALID: {args.csv} ({report['row_count']} rows, {report['required_interval_minutes']}-minute interval)")
        print(f"SHA-256: {report['sha256']}")
        print(f"Time range: {report['first_timestamp']} → {report['last_timestamp']}")
        print("Validity covers structure and interval consistency only, not data provenance.")
    else:
        print(f"INVALID: {args.csv} contains {report['irregular_interval_count']} irregular intervals", file=sys.stderr)
        for gap in report["irregular_intervals"][:5]:
            print(f"  {gap['from']} -> {gap['to']}: {gap['seconds']} seconds", file=sys.stderr)
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
