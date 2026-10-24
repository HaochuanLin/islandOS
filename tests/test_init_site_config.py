from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "init_site_config.py"


class SiteConfigBootstrapTests(unittest.TestCase):
    def run_cli(self, *args: str):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_creates_valid_named_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site.json"
            result = self.run_cli("--site-name", "Demo island", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(config["metadata"]["name"], "Demo island")
        self.assertEqual(config["metadata"]["status"], "illustrative_bootstrap_not_site_data")
        self.assertIn("not measured site data", config["metadata"]["notes"])

    def test_bootstrapped_config_passes_all_first_run_auditors(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site.json"
            audit_path = Path(directory) / "audit.json"
            created = self.run_cli("--site-name", "Pilot sandbox", "--output", str(output))
            self.assertEqual(created.returncode, 0, created.stderr)

            validate = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "validate_site_config.py"),
                 str(output), "--json"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr + validate.stdout)
            validated = json.loads(validate.stdout)
            self.assertTrue(validated["valid"])
            self.assertEqual(validated["name"], "Pilot sandbox")
            self.assertEqual(validated["status"], "illustrative_bootstrap_not_site_data")

            doctor = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "islandos_doctor.py"),
                 "--json", "--config", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr + doctor.stdout)
            diagnosed = json.loads(doctor.stdout)
            self.assertEqual(diagnosed["status"], "ready_for_local_smoke_tests")
            config_check = next(item for item in diagnosed["checks"]
                                if item["id"] == "site_configuration")
            self.assertEqual(config_check["status"], "pass")

            audit = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "audit_site_config.py"),
                 str(output), "--output", str(audit_path)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(audit.returncode, 0, audit.stderr + audit.stdout)
            audited = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audited["metadata"]["name"], "Pilot sandbox")
            self.assertEqual(audited["metadata"]["status"], "illustrative_bootstrap_not_site_data")
            self.assertTrue(audited["provenance_review"]["appears_illustrative_or_assumed"])
            self.assertEqual(
                audited["configuration_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )

    def test_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site.json"
            output.write_text('{"preserve": true}', encoding="utf-8")
            result = self.run_cli("--site-name", "Demo", "--output", str(output))
            self.assertEqual(result.returncode, 2)
            self.assertIn("already exists", result.stderr)
            self.assertEqual(json.loads(output.read_text()), {"preserve": True})

    def test_blank_site_name_is_rejected(self):
        result = self.run_cli("--site-name", "   ")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must not be blank", result.stderr)


if __name__ == "__main__":
    unittest.main()
