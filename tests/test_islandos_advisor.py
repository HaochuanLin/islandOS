"""End-to-end tests for recommendation-only dispatch advisor."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RECEIVED = "2026-10-23T07:00:00Z"


class TestIslandOSAdvisorCLI(unittest.TestCase):
    def test_valid_hourly_telemetry_produces_four_policy_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "advisor-report.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_advisor.py"),
                 str(ROOT / "data/examples/telemetry_replay_demo.csv"),
                 "--max-age-seconds", "7200", "--received-at", RECEIVED, "--output", str(output)],
                text=True, capture_output=True, check=False,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["status"], "advice_ready")
        self.assertEqual(report["row_count"], 3)
        self.assertEqual(len(report["policy_comparison"]), 4)
        self.assertEqual(
            {row["weight_profile"] for row in report["weight_sensitivity"]},
            {"balanced", "water_priority", "cooling_priority", "energy_efficiency"},
        )
        self.assertEqual(sum(report["weight_sensitivity_winner_counts"].values()), 4)
        self.assertIn("not statistical confidence", report["weight_sensitivity_interpretation"])
        for row in report["weight_sensitivity"]:
            self.assertAlmostEqual(sum(row["weights"].values()), 1.0)
            self.assertIn(row["winner_for_this_input"], {"rolling", "ro_first", "ice_first"})
        self.assertEqual(set(report["hourly_audit_by_policy"]), {
            "rolling", "ro_first", "ice_first", "perfect_information"
        })
        self.assertIn(report["recommended_policy_for_operator_review"], {"rolling", "ro_first", "ice_first"})
        self.assertTrue(report["operator_action_required"])
        self.assertFalse(report["physical_write_performed"])

    def test_invalid_telemetry_is_rejected_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.csv"
            source.write_text(
                "timestamp_utc,renewable_surplus_kw,water_demand_m3,cooling_demand_kw_th\n"
                "2026-10-23T05:00:00Z,-1,4,7\n"
                "2026-10-23T06:00:00Z,10,5,8\n",
                encoding="utf-8",
            )
            output = Path(tmp) / "report.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_advisor.py"), str(source),
                 "--max-age-seconds", "3600", "--received-at", "2026-10-23T06:00:00Z", "--output", str(output)],
                text=True, capture_output=True, check=False,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["status"], "rejected")
        self.assertNotIn("policy_comparison", report)
        self.assertFalse(report["physical_write_performed"])

    def test_irregular_time_steps_are_rejected_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "irregular.csv"
            source.write_text(
                "timestamp_utc,renewable_surplus_kw,water_demand_m3,cooling_demand_kw_th\n"
                "2026-10-23T05:00:00Z,20,4,7\n"
                "2026-10-23T06:30:00Z,25,5,8\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_advisor.py"), str(source),
                 "--max-age-seconds", "5400", "--received-at", "2026-10-23T06:30:00Z"],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly one-hour intervals", result.stderr)

    def test_help_does_not_require_input_file(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "islandos_advisor.py"), "--help"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("recommendation-only", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
