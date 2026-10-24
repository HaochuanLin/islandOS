from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.verify_synthetic_artifacts import verify_artifacts


class VerifySyntheticArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv_path = self.root / "sample.csv"
        self.manifest_path = self.root / "sample.manifest.json"
        self.columns = ["timestamp", "renewable_surplus_kw", "water_demand_m3"]
        with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows([
                {"timestamp": "2026-01-01T00:00", "renewable_surplus_kw": "2.0", "water_demand_m3": "1.0"},
                {"timestamp": "2026-01-01T01:00", "renewable_surplus_kw": "3.0", "water_demand_m3": "1.2"},
            ])
        self.write_manifest()

    def write_manifest(self) -> None:
        rows = list(csv.DictReader(self.csv_path.open(encoding="utf-8", newline="")))
        raw = self.csv_path.read_bytes()
        manifest = {
            "dataset_type": "synthetic",
            "is_measured_site_data": False,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "row_count": len(rows),
            "columns": self.columns,
            "time_range": {
                "first_timestamp": rows[0]["timestamp"],
                "last_timestamp": rows[-1]["timestamp"],
                "timezone": "not encoded; timestamps are naive local time",
            },
        }
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_valid_pair_passes(self) -> None:
        self.assertEqual(verify_artifacts(self.csv_path, self.manifest_path), [])

    def test_tampered_csv_fails_hash_check(self) -> None:
        self.csv_path.write_text(self.csv_path.read_text() + "\n", encoding="utf-8")
        errors = verify_artifacts(self.csv_path, self.manifest_path)
        self.assertTrue(any("SHA-256 mismatch" in error for error in errors))

    def test_wrong_row_count_fails(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        manifest["row_count"] = 99
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        errors = verify_artifacts(self.csv_path, self.manifest_path)
        self.assertTrue(any("row count mismatch" in error for error in errors))

    def test_measured_data_claim_is_rejected(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        manifest["is_measured_site_data"] = True
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        errors = verify_artifacts(self.csv_path, self.manifest_path)
        self.assertTrue(any("must explicitly set" in error for error in errors))

    def test_cli_returns_nonzero_for_missing_manifest(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/verify_synthetic_artifacts.py", str(self.csv_path),
             "--manifest", str(self.root / "missing.json")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR:", result.stderr)


if __name__ == "__main__":
    unittest.main()
