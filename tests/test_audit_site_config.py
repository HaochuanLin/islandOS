from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.audit_site_config import audit_config

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "site_parameters.example.json"


class SiteConfigAuditTests(unittest.TestCase):
    def test_audit_hash_matches_exact_bytes_and_reports_cost_gaps(self) -> None:
        report = audit_config(EXAMPLE)
        self.assertEqual(report["configuration_sha256"], hashlib.sha256(EXAMPLE.read_bytes()).hexdigest())
        self.assertTrue(report["provenance_review"]["status_label_present"])
        self.assertTrue(report["provenance_review"]["appears_illustrative_or_assumed"])
        self.assertFalse(report["economics_completeness"]["complete_for_current_declared_fields"])
        self.assertIn("The configuration SHA-256", " ".join(report["limitations"]))

    def test_missing_provenance_labels_are_not_inherited_from_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "site.json"
            config = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            config["metadata"].pop("status", None)
            config["metadata"].pop("notes", None)
            config_path.write_text(json.dumps(config), encoding="utf-8")
            report = audit_config(config_path)
        self.assertFalse(report["provenance_review"]["status_label_present"])
        self.assertFalse(report["provenance_review"]["appears_illustrative_or_assumed"])
        self.assertEqual(report["metadata"]["status"], "unspecified")

    def test_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit" / "config-audit.json"
            result = subprocess.run(
                [sys.executable, "tools/audit_site_config.py", str(EXAMPLE), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["audit_version"], 1)
            self.assertEqual(report["configuration_file"], EXAMPLE.name)

    def test_invalid_config_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "invalid.json"
            config.write_text('{"config_version": 99}', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "tools/audit_site_config.py", str(config)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("CONFIG AUDIT FAILED", result.stderr)


if __name__ == "__main__":
    unittest.main()
