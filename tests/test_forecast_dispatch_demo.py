"""Regression tests for the forecast-to-dispatch demo."""
import csv
import json
import math
from datetime import datetime
from pathlib import Path

import pytest

from tools.generate_synthetic_site_csv import FIELDS, generate_rows
from tools.run_forecast_dispatch_demo import load_rows, main


def write_input(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_synthetic_run_exports_forecast_dispatch_audit(tmp_path: Path) -> None:
    out = tmp_path / "run"
    assert main(["--hours", "30", "--seed", "20261024", "--output-dir", str(out)]) == 0
    report = json.loads((out / "run_report.json").read_text(encoding="utf-8"))
    assert report["dataset_type"] == "synthetic"
    assert report["is_measured_site_data"] is False
    assert report["time_alignment"]["forecast_rows_compared"] == 6
    assert report["forecast"]["model_id"] == "trailing-day-mean"
    assert math.isfinite(report["forecast"]["mae_m3_per_hour"])
    assert len(report["input"]["sha256"]) == 64
    with (out / "strategy_comparison.csv").open(newline="", encoding="utf-8") as handle:
        summaries = list(csv.DictReader(handle))
    assert len(summaries) == 10
    assert {row["demand_basis"] for row in summaries} == {"rolling_forecast", "realized_demand_reference"}
    with (out / "forecast_audit.csv").open(newline="", encoding="utf-8") as handle:
        audit = list(csv.DictReader(handle))
    assert len(audit) == 6
    assert all(len(row["input_history_sha256"]) == 64 for row in audit)


def test_short_input_is_rejected(tmp_path: Path) -> None:
    path = write_input(tmp_path / "short.csv", generate_rows(24, 4, datetime(2026, 1, 1)))
    with pytest.raises(ValueError, match="At least 25 hourly rows"):
        load_rows(path, "UTC")


def test_naive_input_requires_explicit_timezone(tmp_path: Path) -> None:
    path = write_input(tmp_path / "naive.csv", generate_rows(25, 4, datetime(2026, 1, 1)))
    with pytest.raises(ValueError, match="has no timezone"):
        load_rows(path, None)
    _, stamps = load_rows(path, "UTC")
    assert stamps[0].utcoffset() is not None


def test_non_hourly_input_is_rejected(tmp_path: Path) -> None:
    rows = generate_rows(25, 4, datetime(2026, 1, 1))
    rows[7]["timestamp"] = "2026-01-01T08:00:00"
    path = write_input(tmp_path / "gap.csv", rows)
    with pytest.raises(ValueError, match="continuous hourly"):
        load_rows(path, "UTC")


def test_non_finite_demand_is_rejected(tmp_path: Path) -> None:
    rows = generate_rows(25, 4, datetime(2026, 1, 1))
    rows[3]["water_demand_m3"] = "nan"
    path = write_input(tmp_path / "nan.csv", rows)
    with pytest.raises(ValueError, match="finite and non-negative"):
        load_rows(path, "UTC")
