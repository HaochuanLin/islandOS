import unittest

import numpy as np

from islandos_core.energy_balance import (
    BatterySpec,
    EnergyBalanceError,
    simulate_energy_balance,
)


class EnergyBalanceTests(unittest.TestCase):
    def test_renewable_first_conserves_energy_and_reports_grid_import(self):
        result = simulate_energy_balance(
            [10, 10], [6, 14], grid_import_limit_kw=10,
            grid_price_per_kwh=0.5,
        )
        np.testing.assert_allclose(result.renewable_used_kw, [6, 10])
        np.testing.assert_allclose(result.grid_import_kw, [4, 0])
        np.testing.assert_allclose(result.curtailment_kw, [0, 4])
        self.assertAlmostEqual(result.total_cost, 2.0)
        self.assertAlmostEqual(result.total_unmet_energy_kwh, 0.0)
        self.assertAlmostEqual(result.total_curtailment_kwh, 4.0)

    def test_battery_charges_from_surplus_then_discharges_with_efficiency(self):
        battery = BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            charge_efficiency=1, discharge_efficiency=1,
            min_soc_fraction=0, max_soc_fraction=1, initial_soc_fraction=0,
        )
        result = simulate_energy_balance(
            [0, 5], [5, 0], grid_import_limit_kw=0, battery=battery,
        )
        np.testing.assert_allclose(result.battery_charge_kw, [5, 0])
        np.testing.assert_allclose(result.battery_discharge_kw, [0, 5])
        np.testing.assert_allclose(result.battery_soc_kwh, [0, 5, 0])
        self.assertAlmostEqual(result.total_unmet_energy_kwh, 0.0)

    def test_grid_first_is_an_explicit_comparison_baseline(self):
        renewable_first = simulate_energy_balance(
            [10], [10], grid_import_limit_kw=10, grid_price_per_kwh=1,
        )
        grid_first = simulate_energy_balance(
            [10], [10], grid_import_limit_kw=10, grid_price_per_kwh=1,
            strategy="grid_first",
        )
        self.assertEqual(renewable_first.total_grid_energy_kwh, 0)
        self.assertEqual(grid_first.total_grid_energy_kwh, 10)
        self.assertEqual(grid_first.total_curtailment_kwh, 10)

    def test_limited_supply_is_reported_as_unmet_not_hidden(self):
        result = simulate_energy_balance([12], [3], grid_import_limit_kw=4)
        self.assertAlmostEqual(result.load_served_kw[0], 7)
        self.assertAlmostEqual(result.unmet_load_kw[0], 5)
        self.assertAlmostEqual(result.total_unmet_energy_kwh, 5)

    def test_diesel_cost_is_separate_from_grid_cost(self):
        result = simulate_energy_balance(
            [8], [2], grid_import_limit_kw=3, grid_price_per_kwh=0.2,
            diesel_limit_kw=5, diesel_cost_per_kwh=1.5,
        )
        self.assertAlmostEqual(result.total_grid_energy_kwh, 3)
        self.assertAlmostEqual(result.total_diesel_energy_kwh, 3)
        self.assertAlmostEqual(result.total_cost, 5.1)

    def test_rejects_mismatched_series_and_invalid_values(self):
        with self.assertRaises(EnergyBalanceError):
            simulate_energy_balance([1, 2], [1])
        with self.assertRaises(EnergyBalanceError):
            simulate_energy_balance([True], [1])
        with self.assertRaises(EnergyBalanceError):
            simulate_energy_balance([1], [-1])
        with self.assertRaises(EnergyBalanceError):
            simulate_energy_balance([1], [1], dt_hours=0)

    def test_rejects_invalid_battery_soc_envelope(self):
        with self.assertRaises(EnergyBalanceError):
            BatterySpec(
                capacity_kwh=10, max_charge_kw=2, max_discharge_kw=2,
                min_soc_fraction=0.8, max_soc_fraction=0.2,
            )

    def test_zero_renewable_has_defined_utilization(self):
        result = simulate_energy_balance([1], [0], grid_import_limit_kw=1)
        self.assertEqual(result.renewable_utilization_fraction, 1.0)


if __name__ == "__main__":
    unittest.main()
