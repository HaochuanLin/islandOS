"""Tests for the SOWEKI public water-demand data adapter."""
import csv
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.prepare_soweki_water_demand import prepare_soweki_water_demand


class TestPrepareSowekiWaterDemand(unittest.TestCase):
    def _write_quarter_hourly(self, path: Path, hours: int = 60, missing_index: int | None = None):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "value"])
            writer.writeheader()
            for index in range(hours * 4):
                if index == missing_index:
                    continue
                stamp = start + timedelta(minutes=15 * index)
                writer.writerow({
                    "timestamp": stamp.isoformat().replace("+00:00", "Z"),
                    "value": float(index % 8 + 1),
                })

    def test_converts_complete_quarters_to_hourly_series_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "hourly.csv"
            report_path = Path(directory) / "report.json"
            self._write_quarter_hourly(source)
            report = prepare_soweki_water_demand(source, output, report_path)

            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 60)
            self.assertEqual(rows[0]["timestamp"], "2025-01-01T00:00:00Z")
            self.assertAlmostEqual(float(rows[0]["water_demand_m3"]), 2.5)
            self.assertEqual(report["source_rows"], 240)
            self.assertEqual(report["selected_contiguous_hours"], 60)
            self.assertEqual(report["source_file_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(report["prepared_hourly_csv_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(len(report["source_file_sha256"]), 64)
            self.assertEqual(len(report["prepared_hourly_csv_sha256"]), 64)
            self.assertEqual(json.loads(report_path.read_text())["status"], "prepared")

    def test_drops_incomplete_hour_without_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "hourly.csv"
            self._write_quarter_hourly(source, hours=100, missing_index=100)
            report = prepare_soweki_water_demand(source, output, min_hours=48)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 74)
            self.assertEqual(report["incomplete_hour_bins_excluded"], 1)
            self.assertEqual(report["selected_contiguous_hours"], 74)
            # The longest-run requirement must fail rather than stitch over the gap.
            self.assertGreaterEqual(report["selected_contiguous_hours"], 48)

    def test_sorts_out_of_order_rows_and_deduplicates_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "hourly.csv"
            self._write_quarter_hourly(source, hours=60)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows.insert(20, dict(rows[19]))  # exact duplicate record
            rows[50], rows[51] = rows[51], rows[50]  # out-of-order but recoverable
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "value"])
                writer.writeheader()
                writer.writerows(rows)

            report = prepare_soweki_water_demand(source, output)
            with output.open(encoding="utf-8", newline="") as handle:
                hourly = list(csv.DictReader(handle))

            self.assertEqual(len(hourly), 60)
            self.assertEqual(report["source_rows"], 241)
            self.assertEqual(report["unique_timestamp_samples"], 240)
            self.assertEqual(report["exact_duplicate_rows_deduplicated"], 1)
            self.assertGreaterEqual(report["source_non_increasing_adjacent_pairs"], 2)

    def test_rejects_conflicting_duplicate_timestamp_values(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            self._write_quarter_hourly(source, hours=60)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            conflicting = dict(rows[0])
            conflicting["value"] = "999"
            rows.insert(1, conflicting)
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "value"])
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaisesRegex(ValueError, "Conflicting values for duplicate timestamp"):
                prepare_soweki_water_demand(source, Path(directory) / "hourly.csv")

    def test_rejects_naive_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_text(
                "timestamp,value\n2025-01-01T00:00:00,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "timezone"):
                prepare_soweki_water_demand(source, Path(directory) / "out.csv")

    def test_excludes_negative_rate_and_incomplete_hour_without_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "hourly.csv"
            self._write_quarter_hourly(source, hours=60)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["value"] = "-1"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "value"])
                writer.writeheader()
                writer.writerows(rows)

            report = prepare_soweki_water_demand(source, output)
            with output.open(encoding="utf-8", newline="") as handle:
                hourly = list(csv.DictReader(handle))

            self.assertEqual(report["invalid_value_rows_excluded"], 1)
            self.assertEqual(report["invalid_value_examples"][0]["reason"], "negative")
            self.assertEqual(report["partially_observed_hour_bins_excluded"], 1)
            self.assertEqual(report["selected_contiguous_hours"], 59)
            self.assertEqual(len(hourly), 59)
            self.assertEqual(hourly[0]["timestamp"], "2025-01-01T01:00:00Z")

    def test_excludes_non_numeric_and_non_finite_rates_with_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            self._write_quarter_hourly(source, hours=60)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["value"] = "not-a-number"
            rows[1]["value"] = "NaN"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "value"])
                writer.writeheader()
                writer.writerows(rows)

            report = prepare_soweki_water_demand(source, Path(directory) / "hourly.csv")
            self.assertEqual(report["invalid_value_rows_excluded"], 2)
            self.assertEqual(
                {row["reason"] for row in report["invalid_value_examples"]},
                {"not_numeric", "non_finite"},
            )
            self.assertEqual(report["partially_observed_hour_bins_excluded"], 1)
            self.assertEqual(report["selected_contiguous_hours"], 59)

    def test_rejects_duplicate_and_extra_csv_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "hourly.csv"
            source.write_text(
                "timestamp,timestamp\n2025-01-01T00:00:00Z,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate columns"):
                prepare_soweki_water_demand(source, output)

            self._write_quarter_hourly(source)
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[1] += ",unexpected"
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra fields"):
                prepare_soweki_water_demand(source, output)
