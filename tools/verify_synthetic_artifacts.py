#!/usr/bin/env python3
"""Verify a synthetic IslandOS CSV against its provenance manifest.

This checks byte identity and internal consistency only. It cannot establish that
values are measured, physically accurate, or suitable for operational decisions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def verify_artifacts(csv_path: Path, manifest_path: Path) -> list[str]:
    """Return human-readable errors; an empty list means consistency checks passed."""
    errors: list[str] = []
    try:
        raw = csv_path.read_bytes()
    except OSError as exc:
        return [f"cannot read CSV: {exc}"]
    try:
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"cannot read manifest JSON: {exc}"]

    digest = hashlib.sha256(raw).hexdigest()
    if manifest.get("dataset_type") != "synthetic":
        errors.append("manifest dataset_type must be 'synthetic'")
    if manifest.get("is_measured_site_data") is not False:
        errors.append("manifest must explicitly set is_measured_site_data to false")
    if manifest.get("sha256") != digest:
        errors.append(f"SHA-256 mismatch: manifest={manifest.get('sha256')!r}, actual={digest}")

    try:
        with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        return errors + [f"cannot parse CSV: {exc}"]

    if not columns:
        errors.append("CSV is missing a header")
        return errors
    if len(columns) != len(set(columns)):
        errors.append("CSV contains duplicate column names")
    if manifest.get("columns") != columns:
        errors.append("manifest columns do not match CSV header")
    if manifest.get("row_count") != len(rows):
        errors.append(f"row count mismatch: manifest={manifest.get('row_count')!r}, actual={len(rows)}")

    time_range = manifest.get("time_range")
    if not isinstance(time_range, dict):
        errors.append("manifest time_range must be an object")
    elif rows and "timestamp" in rows[0]:
        if time_range.get("first_timestamp") != rows[0].get("timestamp"):
            errors.append("manifest first_timestamp does not match CSV")
        if time_range.get("last_timestamp") != rows[-1].get("timestamp"):
            errors.append("manifest last_timestamp does not match CSV")
    elif rows:
        errors.append("CSV has no timestamp column")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path, help="synthetic CSV to verify")
    parser.add_argument(
        "--manifest", type=Path,
        help="manifest JSON (default: <csv_file stem>.manifest.json)",
    )
    args = parser.parse_args(argv)
    manifest_path = args.manifest or args.csv_file.with_suffix(".manifest.json")
    errors = verify_artifacts(args.csv_file, manifest_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"FAILED: {len(errors)} artifact consistency check(s)", file=sys.stderr)
        return 2
    print(f"OK: {args.csv_file} matches {manifest_path}")
    print("Scope: integrity and internal consistency only; authenticity is not verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
