"""Tests for the reproducible schedule-screening CLI report."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

SPEC = importlib.util.spec_from_file_location(
    "run_schedule_screening_demo", TOOLS / "run_schedule_screening_demo.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ScheduleScreeningDemoTests(unittest.TestCase):
    def test_report_exports_ranked_csv_and_json_with_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            report = MODULE.run_screening(24, 20261105, directory)
            self.assertEqual(
                report["data_provenance"],
                "synthetic_demo_data_not_measured_site_data",
            )
            self.assertEqual(len(report["candidates"]), 3)
            self.assertEqual(
                [row["rank"] for row in report["candidates"]],
                [1, 2, 3],
            )
            self.assertTrue((Path(directory) / "schedule_screening.csv").is_file())
            self.assertTrue((Path(directory) / "schedule_screening.json").is_file())

    def test_rejects_empty_horizon(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                MODULE.run_screening(0, 20261105, directory)


if __name__ == "__main__":
    unittest.main()
