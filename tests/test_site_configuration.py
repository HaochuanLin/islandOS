"""Tests for explicit, validated operator-provided site assumptions."""
import unittest

from islandos_core.configuration import ConfigurationError, SiteConfiguration


VALID = {
    "site_id": "demo-site",
    "water_demand_m3_per_day": 100,
    "ro_capacity_m3_per_day": 120,
    "energy_price_per_kwh": 0.18,
    "ro_specific_energy_kwh_per_m3": 3.5,
    "storage_capacity_m3": 50,
    "initial_storage_m3": 20,
}


class SiteConfigurationTests(unittest.TestCase):
    def test_valid_configuration_round_trips(self):
        config = SiteConfiguration.from_mapping(VALID)
        self.assertEqual(config.site_id, "demo-site")
        self.assertEqual(config.initial_storage_m3, 20.0)
        self.assertEqual(SiteConfiguration.from_mapping(config.to_mapping()), config)

    def test_required_fields_are_reported(self):
        with self.assertRaisesRegex(ConfigurationError, "site_id"):
            SiteConfiguration.from_mapping({"water_demand_m3_per_day": 10})

    def test_negative_or_nonfinite_values_are_rejected(self):
        for value in (-1, float("nan"), float("inf")):
            with self.subTest(value=value):
                data = dict(VALID, water_demand_m3_per_day=value)
                with self.assertRaisesRegex(ConfigurationError, "finite and >= 0"):
                    SiteConfiguration.from_mapping(data)

    def test_initial_storage_cannot_exceed_capacity(self):
        data = dict(VALID, initial_storage_m3=51)
        with self.assertRaisesRegex(ConfigurationError, "cannot exceed"):
            SiteConfiguration.from_mapping(data)

    def test_empty_site_id_is_rejected(self):
        with self.assertRaisesRegex(ConfigurationError, "site_id is required"):
            SiteConfiguration.from_mapping(dict(VALID, site_id="  "))

    def test_unknown_fields_are_not_silently_accepted(self):
        with self.assertRaisesRegex(ConfigurationError, "invalid configuration fields"):
            SiteConfiguration.from_mapping(dict(VALID, unreviewed_setting=7))


if __name__ == "__main__":
    unittest.main()
