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

    def test_custom_device_mapping_normalizes_vendor_keys_and_units(self):
        row = {
            "timestamp": RECEIVED,
            "pv_surplus_w": 25000,
            "freshwater_demand_l": 4000,
            "cooling_wth": 7000,
            "device_id": "vendor-box",
            "quality_flag": "good",
        }
        mapping = {
            "schema_version": 1,
            "fields": {
                "timestamp_utc": {"source_key": "timestamp", "source_unit": "ISO-8601", "canonical_unit": "ISO-8601"},
                "renewable_surplus_kw": {"source_key": "pv_surplus_w", "source_unit": "W", "canonical_unit": "kW", "scale": 0.001},
                "water_demand_m3": {"source_key": "freshwater_demand_l", "source_unit": "L", "canonical_unit": "m3", "scale": 0.001},
                "cooling_demand_kw_th": {"source_key": "cooling_wth", "source_unit": "W_th", "canonical_unit": "kW_th", "scale": 0.001},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "vendor.jsonl"
            map_path = Path(tmp) / "mapping.json"
            source.write_text(json.dumps(row) + "\n", encoding="utf-8")
            map_path.write_text(json.dumps(mapping), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "islandos_gateway.py"), str(source),
                 "--mapping", str(map_path), "--received-at", RECEIVED],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["valid"])
        self.assertEqual(output["values"]["renewable_surplus_kw"], 25.0)
        self.assertEqual(output["values"]["water_demand_m3"], 4.0)
        self.assertEqual(output["values"]["cooling_demand_kw_th"], 7.0)

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
