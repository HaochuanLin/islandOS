"""CLI-level reproducibility checks for the integrated microgrid benchmark."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.run_integrated_microgrid_demo import run_demo


class IntegratedMicrogridDemoTests(unittest.TestCase):
    def test_demo_exports_auditable_synthetic_report_and_hourly_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_demo(48, 1234, tmp)
            report_path = Path(tmp) / "benchmark_report.json"
            csv_path = Path(tmp) / "hourly_comparison.csv"
            self.assertTrue(report_path.is_file())
            self.assertTrue(csv_path.is_file())
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["data_provenance"], "synthetic_demo_data_not_measured_site_data")
            self.assertEqual(loaded["seed"], 1234)
            self.assertEqual(loaded["hours"], 48)
            self.assertIn("essential_unserved_kwh", loaded["renewable_only_ro_flex_load"])
            self.assertIn("unmet_water_demand_m3", loaded["no_ro_baseline"])
            self.assertEqual(len(csv_path.read_text(encoding="utf-8").splitlines()), 49)

    def test_same_seed_produces_same_metrics(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = run_demo(36, 77, a)
            second = run_demo(36, 77, b)
            self.assertEqual(first["no_ro_baseline"], second["no_ro_baseline"])
            self.assertEqual(first["renewable_only_ro_flex_load"], second["renewable_only_ro_flex_load"])


if __name__ == "__main__":
    unittest.main()
