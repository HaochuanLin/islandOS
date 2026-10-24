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
    for artifact in report["artifacts"].values():
        artifact_path = out / artifact["file"]
        assert artifact_path.stat().st_size == artifact["bytes"]
        import hashlib
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact["sha256"]
    with (out / "strategy_comparison.csv").open(newline="", encoding="utf-8") as handle:
        summaries = list(csv.DictReader(handle))
    assert len(summaries) == 10
    assert {row["demand_basis"] for row in summaries} == {"rolling_forecast", "realized_demand_reference"}
    with (out / "forecast_audit.csv").open(newline="", encoding="utf-8") as handle:
        audit = list(csv.DictReader(handle))
    assert len(audit) == 6
    assert all(len(row["input_history_sha256"]) == 64 for row in audit)


def test_fixed_seed_reproduces_input_and_csv_artifact_hashes(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    args = ["--hours", "30", "--seed", "41"]
    assert main([*args, "--output-dir", str(first)]) == 0
    assert main([*args, "--output-dir", str(second)]) == 0
    left = json.loads((first / "run_report.json").read_text(encoding="utf-8"))
    right = json.loads((second / "run_report.json").read_text(encoding="utf-8"))
    assert left["input"]["sha256"] == right["input"]["sha256"]
    assert {
        name: item["sha256"] for name, item in left["artifacts"].items()
    } == {
        name: item["sha256"] for name, item in right["artifacts"].items()
    }


def test_non_empty_output_directory_is_preserved_by_default(tmp_path: Path) -> None:
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--hours", "30", "--output-dir", str(out)])
    assert sentinel.read_text(encoding="utf-8") == "user data"


def test_user_supplied_input_is_not_labeled_as_measured(tmp_path: Path) -> None:
    rows = generate_rows(27, 12, datetime(2026, 2, 1))
    for row in rows:
        row["timestamp"] += "+00:00"
    source = write_input(tmp_path / "site.csv", rows)
    out = tmp_path / "user-run"
    assert main(["--input", str(source), "--output-dir", str(out)]) == 0
    report = json.loads((out / "run_report.json").read_text(encoding="utf-8"))
    assert report["dataset_type"] == "user_supplied_unverified"
    assert report["is_measured_site_data"] is None
    assert report["input"]["sha256"]


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

def test_invalid_dispatch_parameters_fail_closed(tmp_path: Path) -> None:
    out = tmp_path / "invalid-config"
    with pytest.raises(SystemExit):
        main([
            "--hours", "25", "--output-dir", str(out),
            "--ro-rated-power-kw", "0",
        ])
    assert not (out / "run_report.json").exists()


def test_plugin_non_finite_prediction_is_rejected(tmp_path: Path, monkeypatch) -> None:
    plugin_module = tmp_path / "bad_forecast_plugin.py"
    plugin_module.write_text(
        "class BadForecast:\n"
        "    model_id = 'bad-forecast'\n"
        "    version = '0.0.1'\n"
        "    def predict(self, history, target_timestamps):\n"
        "        return [float('nan') for _ in target_timestamps]\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    source_rows = generate_rows(25, 9, datetime(2026, 3, 1))
    for row in source_rows:
        row["timestamp"] += "+00:00"
    source = write_input(tmp_path / "source.csv", source_rows)
    out = tmp_path / "bad-plugin-run"
    with pytest.raises(SystemExit):
        main([
            "--input", str(source), "--output-dir", str(out),
            "--plugin", "bad_forecast_plugin:BadForecast",
        ])
    assert not (out / "run_report.json").exists()

def test_plugin_runtime_error_fails_with_cli_error_not_partial_report(tmp_path: Path, monkeypatch) -> None:
    plugin_module = tmp_path / "raising_forecast_plugin.py"
    plugin_module.write_text(
        "class RaisingForecast:\n"
        "    model_id = 'raising-forecast'\n"
        "    version = '0.0.1'\n"
        "    def predict(self, history, target_timestamps):\n"
        "        raise RuntimeError('plugin unavailable')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    source_rows = generate_rows(25, 11, datetime(2026, 4, 1))
    for row in source_rows:
        row["timestamp"] += "+00:00"
    source = write_input(tmp_path / "source-runtime-error.csv", source_rows)
    out = tmp_path / "runtime-error-run"
    with pytest.raises(SystemExit) as exc:
        main([
            "--input", str(source), "--output-dir", str(out),
            "--plugin", "raising_forecast_plugin:RaisingForecast",
        ])
    assert exc.value.code == 2
    assert not (out / "run_report.json").exists()

