"""Tests for equipment-parameter sensitivity analysis."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.parameter_sensitivity import run_sensitivity


class TestParameterSensitivity(unittest.TestCase):
    def test_sensitivity_runs_baseline_and_parameter_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "site.csv"
            output = root / "sensitivity.json"
            fields = [
                "timestamp", "wind_kw", "pv_kw", "critical_load_kw",
                "water_demand_m3", "cooling_demand_kw_th",
            ]
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for i in range(8):
                    writer.writerow({
                        "timestamp": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                        "wind_kw": 350,
                        "pv_kw": 100 if i in (2, 3, 5) else 0,
                        "critical_load_kw": 100,
                        "water_demand_m3": 20,
                        "cooling_demand_kw_th": 50,
                    })
            report = run_sensitivity(
                source, output, source_type="measured",
                population_size=4, generations=1, seed=5,
            )
            self.assertEqual(report["method"], "one-factor-at-a-time")
            self.assertEqual(len(report["runs"]), 9)
            self.assertEqual(report["runs"][0]["scenario"], "baseline")
            self.assertEqual(report["runs"][1]["change"]["parameter"], "equipment.ro.specific_energy_kwh_m3")
            self.assertTrue(output.exists())
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["runs"]), 9)
            self.assertIn("not a probability distribution", " ".join(saved["interpretation_limits"]))


if __name__ == "__main__":
    unittest.main()
