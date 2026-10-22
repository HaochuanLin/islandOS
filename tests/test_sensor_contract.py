import unittest
from datetime import datetime, timezone

from islandos_sensors.contract import validate_message
from islandos_sensors.mock_source import make_mock_message


class SensorContractTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
        self.message = {
            "schema_version": "0.1",
            "site_id": "site-test",
            "device_id": "meter-test-01",
            "signal_id": "pv_power",
            "observed_at": "2026-10-22T07:59:00+00:00",
            "value": 12.5,
            "unit": "kW",
            "quality": "good",
            "source_type": "sensor",
            "raw_reference": "manual-test-fixture",
        }

    def test_valid_message_passes(self):
        self.assertEqual(validate_message(self.message, now=self.now), [])

    def test_missing_timestamp_is_rejected(self):
        del self.message["observed_at"]
        self.assertTrue(any("observed_at" in e for e in validate_message(self.message, now=self.now)))

    def test_timezone_is_required(self):
        self.message["observed_at"] = "2026-10-22T07:59:00"
        self.assertTrue(any("timezone offset" in e for e in validate_message(self.message, now=self.now)))

    def test_stale_message_is_rejected(self):
        self.message["observed_at"] = "2026-10-22T06:00:00+00:00"
        self.assertTrue(any("stale" in e for e in validate_message(self.message, now=self.now, max_age_seconds=60)))

    def test_uncertain_quality_is_rejected(self):
        self.message["quality"] = "uncertain"
        self.assertTrue(any("quality must be" in e for e in validate_message(self.message, now=self.now)))

    def test_unit_mismatch_is_rejected(self):
        self.message["unit"] = "m"
        self.assertTrue(any("unit mismatch" in e for e in validate_message(self.message, now=self.now)))

    def test_non_finite_value_is_rejected(self):
        self.message["value"] = float("nan")
        self.assertTrue(any("finite number" in e for e in validate_message(self.message, now=self.now)))

    def test_mock_source_is_explicitly_synthetic(self):
        message = make_mock_message("pv_power", 1.0, "kW")
        self.assertEqual(message["source_type"], "synthetic")
        self.assertEqual(validate_message(message), [])

    def test_unknown_signal_is_rejected(self):
        self.message["signal_id"] = "random_signal"
        self.assertTrue(any("unsupported signal_id" in e for e in validate_message(self.message, now=self.now)))


if __name__ == "__main__":
    unittest.main()
