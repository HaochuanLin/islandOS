from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "validate_site_csv.py"
FIELDS = [
    "timestamp", "renewable_surplus_kw", "diesel_displacement_potential_kw",
    "grid_price_per_kwh", "off_peak", "grid_available", "water_demand_m3",
]


def write_csv(path: Path, timestamps: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for timestamp in timestamps:
            writer.writerow([timestamp, 1, 0, 0.2, "true", "true", 1.1])


class SiteCsvPreflightTests(unittest.TestCase):
    def run_cli(self, path: Path, *args: str):
        return subprocess.run(
            [sys.executable, str(CLI), str(path), *args],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_hourly_csv_passes_and_emits_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ok.csv"
            write_csv(path, ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T02:00"])
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report["row_count"], 3)
        self.assertEqual(report["irregular_interval_count"], 0)
        self.assertEqual(len(report["sha256"]), 64)

    def test_gap_fails_instead_of_silently_treating_it_as_hourly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gap.csv"
            write_csv(path, ["2026-01-01T00:00", "2026-01-01T02:00"])
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertFalse(report["valid"])
        self.assertEqual(report["irregular_interval_count"], 1)

    def test_malformed_timestamp_fails_with_row_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            write_csv(path, ["not-a-date"])
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Row 2", json.loads(result.stdout)["error"])

    def test_header_only_csv_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            path.write_text(",".join(FIELDS) + "\\n", encoding="utf-8")
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertFalse(report["valid"])
        self.assertIn("at least one data row", report["error"])

    def test_mixed_timezone_modes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.csv"
            write_csv(path, ["2026-01-01T00:00", "2026-01-01T01:00+00:00"])
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("mix timezone-aware", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
