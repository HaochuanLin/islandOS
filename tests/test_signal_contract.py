"""Tests for the independent, fail-closed signal contract."""
from datetime import datetime, timedelta, timezone
import unittest

from islandos_core.signals import SignalReading, SignalValidationError, validate_signal_payload
from islandos_core.virtual_instrument import make_virtual_reading

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def payload(**overrides):
    result = {"signal_id": "renewable_surplus_kw", "value": 12.5, "unit": "kW",
              "timestamp": NOW.isoformat(), "source": "simulator-1", "quality": "good"}
    result.update(overrides)
    return result


class SignalContractTests(unittest.TestCase):
    def test_valid_payload_round_trips(self):
        reading = validate_signal_payload(payload(), expected_unit="kW", now=NOW)
        self.assertEqual(reading.signal_id, "renewable_surplus_kw")
        self.assertEqual(reading.value, 12.5)
        self.assertEqual(SignalReading.from_payload(reading.to_payload()), reading)

    def test_accepts_zulu_timestamp(self):
        reading = validate_signal_payload(payload(timestamp="2026-10-23T12:00:00Z"), expected_unit="kW", now=NOW)
        self.assertEqual(reading.timestamp, NOW)

    def test_missing_field_is_rejected(self):
        item = payload(); del item["unit"]
        with self.assertRaisesRegex(SignalValidationError, "unit"):
            validate_signal_payload(item, expected_unit="kW", now=NOW)

    def test_unit_mismatch_is_rejected(self):
        with self.assertRaisesRegex(SignalValidationError, "unit mismatch"):
            validate_signal_payload(payload(unit="MW"), expected_unit="kW", now=NOW)

    def test_stale_signal_is_rejected(self):
        old = (NOW - timedelta(seconds=301)).isoformat()
        with self.assertRaisesRegex(SignalValidationError, "stale"):
            validate_signal_payload(payload(timestamp=old), expected_unit="kW", now=NOW)

    def test_future_timestamp_is_rejected(self):
        future = (NOW + timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(SignalValidationError, "future"):
            validate_signal_payload(payload(timestamp=future), expected_unit="kW", now=NOW)

    def test_bad_or_uncertain_quality_is_rejected(self):
        for quality in ("bad", "uncertain"):
            with self.subTest(quality=quality):
                with self.assertRaisesRegex(SignalValidationError, "quality"):
                    validate_signal_payload(payload(quality=quality), expected_unit="kW", now=NOW)

    def test_non_finite_and_out_of_range_values_are_rejected(self):
        with self.assertRaisesRegex(SignalValidationError, "finite"):
            validate_signal_payload(payload(value="nan"), expected_unit="kW", now=NOW)
        with self.assertRaisesRegex(SignalValidationError, "above maximum"):
            validate_signal_payload(payload(value=101), expected_unit="kW", now=NOW, max_value=100)
        with self.assertRaisesRegex(SignalValidationError, "below minimum"):
            validate_signal_payload(payload(value=-1), expected_unit="kW", now=NOW, min_value=0)

    def test_timezone_is_required(self):
        with self.assertRaisesRegex(SignalValidationError, "timezone"):
            validate_signal_payload(payload(timestamp="2026-10-23T12:00:00"), expected_unit="kW", now=NOW)

    def test_virtual_instrument_is_explicitly_simulated(self):
        reading = make_virtual_reading("water_demand", 2.0, "m3/h", timestamp=NOW)
        self.assertEqual(reading.source, "virtual-instrument")
        self.assertEqual(reading.value, 2.0)


if __name__ == "__main__":
    unittest.main()
