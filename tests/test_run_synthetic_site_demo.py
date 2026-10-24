from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.validate_site_csv import inspect_csv
from tools.verify_synthetic_artifacts import verify_artifacts

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "run_synthetic_site_demo.py"


class SyntheticSiteDemoTests(unittest.TestCase):
    def test_one_command_emits_auditable_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo"
            result = subprocess.run(
                [sys.executable, str(CLI), "--output-dir", str(output),
                 "--hours", "24", "--seed", "42"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SYNTHETIC SCREENING ONLY", result.stdout)
            expected = {
                "synthetic_site_hourly.csv",
                "synthetic_site_hourly.manifest.json",
                "strategy_summary.csv",
                "timestep_audit.csv",
                "run_report.json",
            }
            self.assertTrue(expected.issubset({p.name for p in output.iterdir()}))
            report = json.loads((output / "run_report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["is_measured_site_data"])
            input_path = output / "synthetic_site_hourly.csv"
            self.assertEqual(
                report["input"]["sha256"],
                hashlib.sha256(input_path.read_bytes()).hexdigest(),
            )
            with (output / "strategy_summary.csv").open(newline="", encoding="utf-8") as handle:
                summary = list(csv.DictReader(handle))
            self.assertEqual(len(summary), 5)
            with (output / "timestep_audit.csv").open(newline="", encoding="utf-8") as handle:
                audit = list(csv.DictReader(handle))
            self.assertGreaterEqual(len(audit), 24)

            # The generated onboarding artifacts must also pass the standalone
            # validators used for operator-supplied files, not only this demo's
            # own output assertions.
            manifest_path = output / "synthetic_site_hourly.manifest.json"
            self.assertEqual(verify_artifacts(input_path, manifest_path), [])
            quality = inspect_csv(input_path, interval_minutes=60)
            self.assertTrue(quality["valid"], quality["irregular_intervals"])
            self.assertEqual(quality["row_count"], 24)
            self.assertEqual(quality["sha256"], report["input"]["sha256"])

    def test_optional_site_config_is_loaded_and_fingerprinted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo"
            config_path = ROOT / "config" / "site_parameters.example.json"
            result = subprocess.run(
                [sys.executable, str(CLI), "--output-dir", str(output),
                 "--hours", "3", "--config", str(config_path)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / "run_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["assumptions"]["tank_capacity_m3"], 500.0)
            self.assertEqual(report["assumptions"]["initial_water_m3"], 150.0)
            self.assertEqual(
                report["assumptions"]["site_config_sha256"],
                hashlib.sha256(config_path.read_bytes()).hexdigest(),
            )

    def test_invalid_physical_configuration_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(CLI), "--output-dir", directory,
                 "--hours", "2", "--tank-capacity-m3", "10", "--initial-water-m3", "11"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("initial_water_m3", result.stderr)


if __name__ == "__main__":
    unittest.main()
