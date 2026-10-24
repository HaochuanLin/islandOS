from __future__ import annotations

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
