from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tools.generate_synthetic_site_csv import FIELDS, generate_rows


class SyntheticSiteCsvTests(unittest.TestCase):
    def test_rows_are_reproducible_and_match_app_schema(self):
        start = datetime(2026, 1, 1)
        first = generate_rows(48, 7, start)
        second = generate_rows(48, 7, start)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 48)
        self.assertEqual(list(first[0]), FIELDS)
        self.assertTrue(all(row["grid_available"] == "true" for row in first))
        self.assertTrue(all(float(row["water_demand_m3"]) >= 0 for row in first))
        self.assertEqual(first[0]["timestamp"], "2026-01-01T00:00")

    def test_invalid_hours_rejected(self):
        for hours in (0, 8785, -1):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                generate_rows(hours, 1, datetime(2026, 1, 1))

    def test_timezone_aware_start_rejected(self):
        with self.assertRaises(ValueError):
            generate_rows(1, 1, datetime.fromisoformat("2026-01-01T00:00:00+00:00"))

    def test_cli_writes_parseable_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site.csv"
            result = subprocess.run(
                [sys.executable, "tools/generate_synthetic_site_csv.py",
                 "--output", str(output), "--hours", "24", "--seed", "9"],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("SYNTHETIC", result.stdout)
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 24)
            self.assertEqual(list(rows[0]), FIELDS)


if __name__ == "__main__":
    unittest.main()
