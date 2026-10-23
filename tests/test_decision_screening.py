"""Tests for the read-only, explainable RO screening heuristic."""
from datetime import datetime, timezone
import json
import unittest

from islandos_core.configuration import SiteConfiguration
from islandos_core.decision import recommend_ro_screening
from islandos_core.signals import SignalReading


NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
CONFIG = SiteConfiguration(
    site_id="test-site",
    water_demand_m3_per_day=100,
    ro_capacity_m3_per_day=120,
    energy_price_per_kwh=0.18,
    ro_specific_energy_kwh_per_m3=3.5,
    storage_capacity_m3=50,
    initial_storage_m3=10,
)


def reading(signal_id, value, unit):
    return SignalReading(signal_id, value, unit, NOW, "test-fixture", "good")


class DecisionScreeningTests(unittest.TestCase):
    def test_low_inventory_and_enough_surplus_suggests_reviewed_run(self):
        result = recommend_ro_screening(
            CONFIG,
            renewable_surplus=reading("renewable_surplus_kw", 20, "kW"),
            water_inventory=reading("water_inventory_m3", 5, "m3"),
        )
        self.assertEqual(result.action, "consider_run_on_surplus")
        self.assertAlmostEqual(result.estimated_full_load_power_kw, 17.5)
        self.assertIn("human review only", " ".join(result.assumptions))

    def test_payload_is_versioned_json_and_explicitly_not_a_command(self):
        result = recommend_ro_screening(
            CONFIG,
            renewable_surplus=reading("renewable_surplus_kw", 20, "kW"),
            water_inventory=reading("water_inventory_m3", 5, "m3"),
        )
        payload = result.to_payload()
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["schema_version"], "1.0")
        self.assertEqual(decoded["mode"], "read_only_screening")
        self.assertIsNone(decoded["control_command"])
        self.assertEqual(decoded["recommendation"]["action"], result.action)
        self.assertIsInstance(decoded["recommendation"]["assumptions"], list)

    def test_low_surplus_holds(self):
        result = recommend_ro_screening(
            CONFIG,
            renewable_surplus=reading("renewable_surplus_kw", 10, "kW"),
            water_inventory=reading("water_inventory_m3", 5, "m3"),
        )
        self.assertEqual(result.action, "hold_and_review")
        self.assertIn("below estimated full-load power", result.reason)

    def test_inventory_at_target_holds(self):
        result = recommend_ro_screening(
            CONFIG,
            renewable_surplus=reading("renewable_surplus_kw", 30, "kW"),
            water_inventory=reading("water_inventory_m3", 25, "m3"),
        )
        self.assertEqual(result.action, "hold_and_review")

    def test_wrong_signal_or_unit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "signal_id"):
            recommend_ro_screening(
                CONFIG,
                renewable_surplus=reading("wrong_signal", 20, "kW"),
                water_inventory=reading("water_inventory_m3", 5, "m3"),
            )
        with self.assertRaisesRegex(ValueError, "unit"):
            recommend_ro_screening(
                CONFIG,
                renewable_surplus=reading("renewable_surplus_kw", 20, "MW"),
                water_inventory=reading("water_inventory_m3", 5, "m3"),
            )

    def test_out_of_range_inventory_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            recommend_ro_screening(
                CONFIG,
                renewable_surplus=reading("renewable_surplus_kw", 20, "kW"),
                water_inventory=reading("water_inventory_m3", 51, "m3"),
            )

    def test_zero_capacity_or_specific_energy_is_rejected(self):
        zero = SiteConfiguration(
            site_id="zero",
            water_demand_m3_per_day=100,
            ro_capacity_m3_per_day=0,
            energy_price_per_kwh=0.18,
            ro_specific_energy_kwh_per_m3=3.5,
            storage_capacity_m3=50,
        )
        with self.assertRaisesRegex(ValueError, "both be > 0"):
            recommend_ro_screening(
                zero,
                renewable_surplus=reading("renewable_surplus_kw", 20, "kW"),
                water_inventory=reading("water_inventory_m3", 5, "m3"),
            )


if __name__ == "__main__":
    unittest.main()
