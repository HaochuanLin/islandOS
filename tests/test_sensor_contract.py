import unittest
from datetime import datetime, timezone

from islandos_sensors.contract import validate_batch, validate_message
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

    def test_future_timestamp_beyond_clock_skew_is_rejected(self):
        self.message["observed_at"] = "2026-10-22T08:06:00+00:00"
        self.assertTrue(any("future" in e for e in validate_message(self.message, now=self.now)))

    def test_any_future_timestamp_is_rejected(self):
        self.message["observed_at"] = "2026-10-22T08:00:00.000001+00:00"
        self.assertTrue(any("future" in e for e in validate_message(self.message, now=self.now)))

    def test_timestamp_must_be_a_string(self):
        self.message["observed_at"] = 1792656000
        self.assertTrue(any("ISO-8601" in e for e in validate_message(self.message, now=self.now)))

    def test_equivalent_timezone_offsets_are_compared_in_utc(self):
        self.message["observed_at"] = "2026-10-22T16:00:00.000001+08:00"
        self.assertTrue(any("future" in e for e in validate_message(self.message, now=self.now)))

    def test_uncertain_quality_is_rejected(self):
        self.message["quality"] = "uncertain"
        self.assertTrue(any("quality must be" in e for e in validate_message(self.message, now=self.now)))

    def test_bad_quality_is_rejected(self):
        self.message["quality"] = "bad"
        self.assertTrue(any("quality must be" in e for e in validate_message(self.message, now=self.now)))

    def test_unit_mismatch_is_rejected(self):
        self.message["unit"] = "m"
        self.assertTrue(any("unit mismatch" in e for e in validate_message(self.message, now=self.now)))

    def test_non_finite_value_is_rejected(self):
        self.message["value"] = float("nan")
        self.assertTrue(any("finite number" in e for e in validate_message(self.message, now=self.now)))

    def test_boolean_is_not_accepted_as_numeric_value(self):
        self.message["value"] = True
        self.assertTrue(any("finite number" in e for e in validate_message(self.message, now=self.now)))

    def test_negative_value_is_rejected(self):
        self.message["value"] = -0.1
        self.assertTrue(any("below the allowed minimum" in e for e in validate_message(self.message, now=self.now)))

    def test_empty_device_identity_is_rejected(self):
        self.message["device_id"] = "   "
        self.assertTrue(any("device_id" in e for e in validate_message(self.message, now=self.now)))

    def test_invalid_max_age_is_rejected(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value):
                self.assertTrue(any("max_age_seconds" in e for e in validate_message(
                    self.message, now=self.now, max_age_seconds=value
                )))

    def test_mock_source_is_explicitly_synthetic(self):
        message = make_mock_message("pv_power", 1.0, "kW")
        self.assertEqual(message["source_type"], "synthetic")
        self.assertEqual(validate_message(message), [])

    def test_unknown_signal_is_rejected(self):
        self.message["signal_id"] = "random_signal"
        self.assertTrue(any("unsupported signal_id" in e for e in validate_message(self.message, now=self.now)))

    def test_unknown_source_type_is_rejected(self):
        self.message["source_type"] = "imagined"
        self.assertTrue(any("unsupported source_type" in e for e in validate_message(self.message, now=self.now)))

    def test_invalid_message_type_is_rejected(self):
        self.assertTrue(validate_message(None, now=self.now))


    def test_batch_quarantines_duplicate_sample_identity(self):
        first = dict(self.message)
        second = dict(self.message, value=13.0)
        results = validate_batch([first, second], now=self.now)
        self.assertFalse(results[0]["valid"])
        self.assertFalse(results[1]["valid"])
        self.assertTrue(any("duplicate sample identity" in e for e in results[0]["errors"]))
        self.assertTrue(any("duplicate sample identity" in e for e in results[1]["errors"]))

    def test_batch_preserves_distinct_samples(self):
        first = dict(self.message)
        second = dict(self.message, observed_at="2026-10-22T07:58:00+00:00")
        results = validate_batch([first, second], now=self.now)
        self.assertTrue(all(item["valid"] for item in results))

    def test_batch_rejects_non_sequence(self):
        with self.assertRaises(ValueError):
            validate_batch({"not": "a sequence"}, now=self.now)

    def test_batch_detects_same_instant_with_different_timezone_offsets(self):
        first = dict(self.message)
        second = dict(self.message, observed_at="2026-10-22T08:59:00+01:00")
        results = validate_batch([first, second], now=self.now)
        self.assertFalse(results[0]["valid"])
        self.assertFalse(results[1]["valid"])


if __name__ == "__main__":
    unittest.main()
