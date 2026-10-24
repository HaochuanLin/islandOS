"""Regression tests for input provenance and CSV schema validation."""
import csv
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from experiments.evaluate_forecast_candidate import evaluate_candidate


def _write_hourly_csv(path, *, duplicate_header=False):
    headers = [
        "timestamp",
        "actual_water_demand_m3",
        "incumbent_forecast_m3",
        "candidate_forecast_m3",
    ]
    if duplicate_header:
        headers[1] = "timestamp"
    start = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for index in range(48):
            actual = 30.0 + (index % 8)
            writer.writerow([
                (start + timedelta(hours=index)).isoformat(),
                actual,
                actual + 2.0,
                actual + 0.2,
            ])


def test_report_records_sha256_of_exact_input_bytes(tmp_path):
    input_csv = tmp_path / "comparison.csv"
    output_json = tmp_path / "report.json"
    _write_hourly_csv(input_csv)

    report = evaluate_candidate(
        input_csv,
        output_json,
        high_demand_threshold_m3=30.0,
        min_high_demand_samples=5,
    )

    assert report["input_csv_sha256"] == hashlib.sha256(input_csv.read_bytes()).hexdigest()
    assert len(report["input_csv_sha256"]) == 64


def test_duplicate_csv_headers_are_rejected(tmp_path):
    input_csv = tmp_path / "duplicate.csv"
    _write_hourly_csv(input_csv, duplicate_header=True)

    with pytest.raises(ValueError, match="duplicate columns"):
        evaluate_candidate(
            input_csv,
            tmp_path / "report.json",
            high_demand_threshold_m3=30.0,
            min_high_demand_samples=5,
        )


def test_extra_csv_fields_are_rejected(tmp_path):
    input_csv = tmp_path / "extra-fields.csv"
    _write_hourly_csv(input_csv)
    lines = input_csv.read_text(encoding="utf-8").splitlines()
    lines[1] += ",unexpected"
    input_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="extra fields"):
        evaluate_candidate(
            input_csv,
            tmp_path / "report.json",
            high_demand_threshold_m3=30.0,
            min_high_demand_samples=5,
        )
