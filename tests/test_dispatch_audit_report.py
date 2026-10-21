"""Tests for machine-readable per-timestep dispatch audits."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.generate_dispatch_report import generate_report


class TestDispatchAuditReport(unittest.TestCase):
    def test_report_contains_passing_hourly_physical_audits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = generate_report(temp_dir)
            audit_path = Path(temp_dir) / "audit_report.json"
            self.assertTrue(audit_path.exists())
            payload = json.loads(audit_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["audit_status"], "pass")
        self.assertEqual(summary["audit_timestep_count"], 96)
        self.assertEqual(payload["timestep_record_count"], 96)
        self.assertEqual(payload["failed_timestep_count"], 0)
        self.assertEqual(payload["overall_status"], "pass")
        for record in payload["timesteps"]:
            self.assertEqual(record["status"], "pass", record)
            self.assertAlmostEqual(record["power_balance_residual_kw"], 0.0, places=7)
            for load in record["loads"].values():
                self.assertAlmostEqual(load["inventory_balance_residual"], 0.0, places=7)
                self.assertAlmostEqual(load["demand_balance_residual"], 0.0, places=7)
                self.assertEqual(load["capacity_violation"], False)
                self.assertEqual(load["constraint_violation"], 0)

    def test_audit_report_is_machine_readable_and_discloses_synthetic_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = generate_report(temp_dir)
            payload = json.loads(
                (Path(temp_dir) / "audit_report.json").read_text(encoding="utf-8")
            )
        self.assertIn("synthetic", payload["data_status"])
        self.assertTrue(payload["checks"])
        self.assertTrue(payload["limitations"])
        self.assertIn("audit_report.json", summary["files"])


if __name__ == "__main__":
    unittest.main()
