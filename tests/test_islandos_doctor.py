"""Regression tests for the offline IslandOS first-run doctor."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "tools" / "islandos_doctor.py"


class TestIslandOSDoctor(unittest.TestCase):
    def test_default_diagnostic_reports_local_readiness(self):
        result = subprocess.run(
            [sys.executable, str(DOCTOR), "--json"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["status"], "ready_for_local_smoke_tests")
        self.assertTrue(all(item["status"] == "pass" for item in report["checks"]))
        self.assertTrue(report["limitations"])

    def test_invalid_custom_config_returns_actionable_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "invalid.json"
            config.write_text('{"equipment":{"ro":{"reservoir_capacity_m3":-1}}}', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(DOCTOR), "--json", "--config", str(config)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "needs_attention")
        config_check = next(item for item in report["checks"] if item["id"] == "site_configuration")
        self.assertEqual(config_check["status"], "fail")
        self.assertIn("reservoir_capacity_m3", config_check["detail"])

    def test_non_object_metadata_is_reported_as_validation_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "metadata-null.json"
            config.write_text(
                json.dumps({
                    "config_version": 1,
                    "metadata": None,
                    "equipment": {
                        "ro": {
                            "specific_energy_kwh_m3": 3.5,
                            "reservoir_capacity_m3": 500,
                            "initial_water_m3": 150,
                            "dead_storage_m3": 20,
                            "allow_backup_power": False,
                        },
                        "ice": {
                            "coefficient_of_performance": 2.5,
                            "storage_capacity_kwh_th": 400,
                            "initial_storage_kwh_th": 100,
                        },
                    },
                    "search_space": {
                        "priority": ["ro_first"],
                        "ro_min_run_hours": [1],
                        "ro_start_ratio": [0.7],
                        "ro_rated_power_kw": [250],
                        "ice_rated_power_kw": [50],
                    },
                    "economics": {},
                }),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(DOCTOR), "--json", "--config", str(config)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        config_check = next(item for item in report["checks"] if item["id"] == "site_configuration")
        self.assertEqual(config_check["status"], "fail")
        self.assertIn("metadata must be an object", config_check["detail"])

    def test_unsupported_python_version_is_a_failure(self):
        # Import the script directly so the runtime check can be tested without
        # running the interpreter itself under an unsupported Python version.
        import importlib.util
        spec = importlib.util.spec_from_file_location("islandos_doctor", DOCTOR)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        report = module.run_doctor(root=ROOT, python_version=(3, 9))
        self.assertEqual(report["status"], "needs_attention")
        runtime = next(item for item in report["checks"] if item["id"] == "python_runtime")
        self.assertEqual(runtime["status"], "fail")


if __name__ == "__main__":
    unittest.main()
