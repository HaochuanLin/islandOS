"""Tests for input signatures used to prevent stale UI results."""
import unittest

from app_state import strategy_run_signature


class TestStrategyRunSignature(unittest.TestCase):
    def setUp(self):
        self.raw = b"timestamp,renewable_surplus_kw\n2026-01-01T00:00:00Z,12\n"
        self.settings = {"ro_rated_power_kw": 10.0, "tank_capacity_m3": 50.0}

    def test_signature_is_deterministic_and_mapping_order_independent(self):
        first = strategy_run_signature(self.raw, "synthetic demo", self.settings)
        second = strategy_run_signature(
            self.raw, "synthetic demo", {"tank_capacity_m3": 50.0, "ro_rated_power_kw": 10.0}
        )
        self.assertEqual(first, second)

    def test_changed_input_data_changes_signature(self):
        baseline = strategy_run_signature(self.raw, "uploaded site.csv", self.settings)
        changed = strategy_run_signature(self.raw + b"\n", "uploaded site.csv", self.settings)
        self.assertNotEqual(baseline, changed)

    def test_changed_model_setting_changes_signature(self):
        baseline = strategy_run_signature(self.raw, "synthetic demo", self.settings)
        changed = strategy_run_signature(
            self.raw, "synthetic demo", {**self.settings, "ro_rated_power_kw": 12.0}
        )
        self.assertNotEqual(baseline, changed)

    def test_changed_data_source_changes_signature(self):
        baseline = strategy_run_signature(self.raw, "synthetic demo", self.settings)
        changed = strategy_run_signature(self.raw, "uploaded site.csv", self.settings)
        self.assertNotEqual(baseline, changed)

    def test_non_finite_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            strategy_run_signature(self.raw, "synthetic demo", {"ro_rated_power_kw": float("nan")})


if __name__ == "__main__":
    unittest.main()
