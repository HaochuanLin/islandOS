"""Integration tests for the read-only telemetry replay CLI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
RECEIVED = "2026-10-23T05:00:00Z"


class TestTelemetryReplayCLI(unittest.TestCase):
    def test_jsonl_valid_message_emits_canonical_audit_record(self):
        row = {
            "timestamp_utc": RECEIVED,
            "device_id": "fixture-gateway",
            "quality_flag": "good",
            "renewable_surplus_kw": 30,
            "water_demand_m3": 4,
            "cooling_demand_kw_th": 7,
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "telemetry.jsonl"
            source.write_text(json.dumps(row) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_gateway.py"), str(source),
                 "--received-at", RECEIVED],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["valid"])
        self.assertEqual(output["row"], 1)
        self.assertEqual(output["values"]["renewable_surplus_kw"], 30.0)

    def test_invalid_message_returns_nonzero_and_emits_rejection(self):
        row = {"timestamp_utc": RECEIVED, "renewable_surplus_kw": -1}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.jsonl"
            source.write_text(json.dumps(row) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_gateway.py"), str(source),
                 "--received-at", RECEIVED],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 2)
        output = json.loads(result.stdout)
        self.assertFalse(output["valid"])
        self.assertTrue(output["errors"])

    def test_csv_replay_uses_same_validator(self):
        csv_text = (
            "timestamp_utc,renewable_surplus_kw,water_demand_m3,cooling_demand_kw_th\n"
            + RECEIVED + ",20,3,6\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "telemetry.csv"
            source.write_text(csv_text, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_gateway.py"), str(source),
                 "--received-at", RECEIVED],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_malformed_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "broken.jsonl"
            source.write_text("{not json}\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_gateway.py"), str(source)],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
