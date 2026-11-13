import json
import tempfile
import unittest
from pathlib import Path

from islandos_shadow import main


class TestShadowReplayCli(unittest.TestCase):
    def test_cli_writes_auditable_within_tolerance_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recommendation = {
                "recommendation_id": "rec-cli",
                "created_at_utc": "2026-11-13T10:00:00Z",
                "signals": {"grid_import_kw": {"value": 8.0, "unit": "kW"}},
            }
            observation = {
                "observation_id": "obs-cli",
                "timestamp_utc": "2026-11-13T10:04:00Z",
                "signals": {"grid_import_kw": {"value": 8.2, "unit": "kW", "tolerance": 0.5}},
            }
            rec_path, obs_path, output_path = root / "rec.json", root / "obs.json", root / "report.json"
            rec_path.write_text(json.dumps(recommendation), encoding="utf-8")
            obs_path.write_text(json.dumps(observation), encoding="utf-8")
            code = main([
                "--recommendation", str(rec_path),
                "--observation", str(obs_path),
                "--evaluated-at-utc", "2026-11-13T10:05:00Z",
                "--output", str(output_path),
            ])
            self.assertEqual(code, 0)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "within_tolerance")
            self.assertFalse(report["device_write_authorized"])
            self.assertEqual(len(report["audit_sha256"]), 64)

    def test_cli_returns_nonzero_for_deviation_and_stale_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec_path, obs_path = root / "rec.json", root / "obs.json"
            rec_path.write_text(json.dumps({
                "recommendation_id": "rec-cli",
                "created_at_utc": "2026-11-13T10:00:00Z",
                "signals": {"battery_kw": {"value": 1.0, "unit": "kW"}},
            }), encoding="utf-8")
            obs_path.write_text(json.dumps({
                "observation_id": "obs-cli",
                "timestamp_utc": "2026-11-13T10:04:00Z",
                "signals": {"battery_kw": {"value": 5.0, "unit": "kW", "tolerance": 0.1}},
            }), encoding="utf-8")
            code = main([
                "--recommendation", str(rec_path),
                "--observation", str(obs_path),
                "--evaluated-at-utc", "2026-11-13T10:05:00Z",
                "--output", str(root / "deviation.json"),
            ])
            self.assertEqual(code, 1)
            code = main([
                "--recommendation", str(rec_path),
                "--observation", str(obs_path),
                "--evaluated-at-utc", "2026-11-13T10:20:00Z",
                "--max-age-seconds", "300",
                "--output", str(root / "blocked.json"),
            ])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
