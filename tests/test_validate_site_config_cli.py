"""Tests for the standalone parameter-configuration validation CLI."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "validate_site_config.py"
EXAMPLE = ROOT / "config" / "site_parameters.example.json"


class ValidateSiteConfigCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), *map(str, args)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_example_config_validates_without_optional_dependencies(self):
        result = self.run_cli(EXAMPLE, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["valid"])
        self.assertFalse(report["economics_complete"])
        self.assertIn("not measured site data", " ".join(report["limitations"]))

    def test_invalid_config_returns_nonzero_and_explains_unknown_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"equipment": {"ro": {"specfic_energy": 4}}}))
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["valid"])
        self.assertIn("Unknown configuration key", json.loads(result.stdout)["error"])

    def test_null_metadata_returns_machine_readable_validation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "null-metadata.json"
            path.write_text(json.dumps({"metadata": None}), encoding="utf-8")
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertFalse(report["valid"])
        self.assertIn("metadata must be an object", report["error"])

    def test_invalid_json_returns_machine_readable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{broken")
            result = self.run_cli(path, "--json")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["valid"])
        self.assertIn("Invalid JSON", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
