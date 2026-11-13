import unittest

from islandos_core.shadow_mode import compare_shadow_run


class TestShadowMode(unittest.TestCase):
    def setUp(self):
        self.recommendation = {
            "recommendation_id": "rec-001",
            "created_at_utc": "2026-11-13T10:00:00Z",
            "signals": {
                "battery_power_kw": {"value": 4.0, "unit": "kW"},
                "ro_power_kw": {"value": 12.0, "unit": "kW"},
            },
        }
        self.observation = {
            "observation_id": "obs-001",
            "timestamp_utc": "2026-11-13T10:04:00Z",
            "signals": {
                "battery_power_kw": {"value": 3.7, "unit": "kW", "tolerance": 0.5},
                "ro_power_kw": {"value": 12.2, "unit": "kW", "tolerance": 0.5},
            },
        }

    def compare(self, **kwargs):
        return compare_shadow_run(
            self.recommendation, self.observation,
            evaluated_at_utc="2026-11-13T10:05:00Z", **kwargs,
        )

    def test_matching_observation_is_read_only_and_auditable(self):
        report = self.compare()
        self.assertEqual(report["status"], "within_tolerance")
        self.assertEqual(len(report["audit_sha256"]), 64)
        self.assertFalse(report["device_write_authorized"])
        self.assertFalse(report["command_generated"])
        self.assertFalse(report["operator_review_required"])

    def test_deviation_requires_operator_review_not_automatic_correction(self):
        self.observation["signals"]["ro_power_kw"]["value"] = 15.0
        report = self.compare()
        self.assertEqual(report["status"], "deviation")
        self.assertTrue(report["operator_review_required"])
        self.assertFalse(report["device_write_authorized"])
        self.assertFalse(report["command_generated"])

    def test_stale_or_missing_observation_fails_closed(self):
        self.observation["timestamp_utc"] = "2026-11-13T09:00:00Z"
        report = self.compare(max_observation_age_seconds=300)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("observation is stale", report["errors"])

        self.observation["timestamp_utc"] = "2026-11-13T10:04:00Z"
        self.observation["signals"].pop("ro_power_kw")
        report = self.compare()
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("missing observed signals" in item for item in report["errors"]))

    def test_unit_mismatch_and_non_finite_values_fail_closed(self):
        self.observation["signals"]["ro_power_kw"]["unit"] = "W"
        report = self.compare()
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("unit mismatch" in item for item in report["errors"]))

        self.observation["signals"]["ro_power_kw"]["unit"] = "kW"
        self.observation["signals"]["ro_power_kw"]["value"] = float("nan")
        report = self.compare()
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["device_write_authorized"])

    def test_future_observation_is_rejected(self):
        self.observation["timestamp_utc"] = "2026-11-13T10:10:00Z"
        report = self.compare()
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("future" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
