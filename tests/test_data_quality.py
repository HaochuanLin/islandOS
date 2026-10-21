"""Regression tests for the CSV data-quality validator."""
import csv
import tempfile
import unittest
from pathlib import Path

from data_quality import REQUIRED_COLUMNS, validate_csv


class TestDataQuality(unittest.TestCase):
    def write_csv(self, rows, columns=REQUIRED_COLUMNS):
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.close()
        return handle.name

    def row(self, timestamp="2026-01-01T00:00:00+00:00", **overrides):
        row = {
            "timestamp": timestamp,
            "wind_kw": "10",
            "pv_kw": "20",
            "critical_load_kw": "30",
            "water_demand_m3": "4",
            "cooling_demand_kw_th": "5",
        }
        row.update(overrides)
        return row

    def test_valid_hourly_csv(self):
        path = self.write_csv([
            self.row(),
            self.row(timestamp="2026-01-01T01:00:00+00:00"),
        ])
        report = validate_csv(path, "public")
        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["row_count"], 2)
        self.assertFalse(report["summary"]["data_was_modified"])

    def test_missing_columns_fail_loudly(self):
        path = self.write_csv([self.row()], columns=("timestamp", "wind_kw"))
        report = validate_csv(path, "measured")
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["issues"][0]["code"], "missing_columns")

    def test_detects_duplicate_and_non_monotonic_timestamps(self):
        path = self.write_csv([
            self.row(),
            self.row(timestamp="2026-01-01T01:00:00+00:00"),
            self.row(timestamp="2026-01-01T01:00:00+00:00"),
            self.row(timestamp="2026-01-01T00:30:00+00:00"),
            self.row(timestamp="2026-01-01T02:30:00+00:00"),
        ])
        codes = validate_csv(path, "synthetic")["issue_codes"]
        self.assertIn("duplicate_timestamp", codes)
        self.assertIn("non_monotonic_timestamp", codes)
        self.assertIn("interval_mismatch", codes)

    def test_detects_bad_values_and_timezone_missing(self):
        path = self.write_csv([
            self.row(timestamp="2026-01-01T00:00:00", wind_kw="-1", pv_kw="nan"),
            self.row(timestamp="2026-01-01T01:00:00Z", water_demand_m3=""),
        ])
        report = validate_csv(path, "forecast")
        codes = report["issue_codes"]
        self.assertIn("invalid_timestamp", codes)
        self.assertIn("negative_value", codes)
        self.assertIn("non_finite", codes)
        self.assertIn("missing_value", codes)

    def test_rejects_unknown_source_type_and_interval(self):
        path = self.write_csv([self.row()])
        with self.assertRaises(ValueError):
            validate_csv(path, "guessed")
        with self.assertRaises(ValueError):
            validate_csv(path, "public", 0)


if __name__ == "__main__":
    unittest.main()
