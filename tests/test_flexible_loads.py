"""Tests for the common flexible-load interface and initial load plug-ins."""
import unittest
import numpy as np

from flexible_loads import (
    FlexibleLoad, IceStorageConfig, IceStorageLoad, ROConfig, ROWaterLoad,
)


class TestFlexibleLoadPlugins(unittest.TestCase):
    def test_ro_and_ice_implement_common_contract(self):
        self.assertIsInstance(ROWaterLoad(), FlexibleLoad)
        self.assertIsInstance(IceStorageLoad(), FlexibleLoad)

    def test_ro_no_backup_refuses_to_start_without_forecast_window(self):
        ro = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=2,
            initial_water_m3=500, dead_storage_m3=0,
            reservoir_capacity_m3=1000, min_run_hours=2,
            allow_backup_power=False,
        ))
        result = ro.simulate([200, 200, 200], [10, 10, 10])
        self.assertEqual(int(result.active.sum()), 0)
        self.assertEqual(int(result.constraint_violation.sum()), 0)

    def test_ro_no_backup_requires_every_forecast_hour_to_be_feasible(self):
        ro = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=2,
            initial_water_m3=500, dead_storage_m3=0,
            reservoir_capacity_m3=1000, min_run_hours=2,
            allow_backup_power=False,
        ))
        forecast = [[100, 20], [20, 100], [100, 100], [100, 100]]
        result = ro.simulate([100, 20, 100, 100], [0, 0, 0, 0],
                             forecast_available_power_kw=forecast)
        self.assertEqual(result.active[0], 0)
        self.assertEqual(result.active[2], 1)
        self.assertEqual(result.active[3], 1)
        self.assertEqual(int(result.constraint_violation.sum()), 0)

    def test_ro_surfaces_forecast_error_and_reports_backup_separately(self):
        no_backup = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=2,
            initial_water_m3=500, dead_storage_m3=0,
            reservoir_capacity_m3=1000, min_run_hours=2,
            allow_backup_power=False,
        ))
        result = no_backup.simulate(
            [100, 20], [0, 0],
            forecast_available_power_kw=[[100, 100], [20, 20]],
        )
        self.assertEqual(result.active[1], 1)
        self.assertEqual(result.constraint_violation[1], 1)

        backed = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=2,
            initial_water_m3=500, dead_storage_m3=0,
            reservoir_capacity_m3=1000, min_run_hours=2,
            allow_backup_power=True, start_ratio=0.8,
        ))
        backed_result = backed.simulate([100, 60], [0, 0])
        self.assertEqual(backed_result.power_used_kw[1], 100)
        self.assertAlmostEqual(backed_result.backup_power_kw[1], 40)
        self.assertEqual(int(backed_result.constraint_violation.sum()), 0)

    def test_ro_water_balance_tracks_unmet_demand_and_inventory(self):
        ro = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=1,
            initial_water_m3=10, dead_storage_m3=5,
            reservoir_capacity_m3=100, min_run_hours=1,
            allow_backup_power=True, start_ratio=0.5,
        ))
        result = ro.simulate([0, 0], [20, 20])
        self.assertAlmostEqual(result.demand_served[0], 5)
        self.assertAlmostEqual(result.unmet_demand[0], 15)
        self.assertAlmostEqual(result.unmet_demand[1], 20)
        self.assertTrue(np.all(result.inventory >= 5 - 1e-9))
        self.assertTrue(np.all(result.inventory <= 100 + 1e-9))

    def test_ice_storage_shifts_surplus_energy_to_later_cooling_demand(self):
        ice = IceStorageLoad(IceStorageConfig(
            rated_power_kw=100, coefficient_of_performance=2,
            storage_capacity_kwh_th=300, initial_storage_kwh_th=0,
        ))
        result = ice.simulate([100, 0, 0], [0, 150, 100])
        self.assertAlmostEqual(result.power_used_kw[0], 100)
        self.assertAlmostEqual(result.resource_produced[0], 200)
        self.assertAlmostEqual(result.demand_served[1], 150)
        self.assertAlmostEqual(result.unmet_demand[1], 0)
        self.assertAlmostEqual(result.unmet_demand[2], 50)
        self.assertTrue(np.all(result.inventory >= 0))
        self.assertTrue(np.all(result.inventory <= 300))

    def test_invalid_input_is_rejected(self):
        ice = IceStorageLoad()
        with self.assertRaises(ValueError):
            ice.simulate([1, -1], [0, 0])
        with self.assertRaises(ValueError):
            ice.simulate([1, 2], [0])
        with self.assertRaises(ValueError):
            ice.simulate([1], [0], dt_hours=0)


if __name__ == "__main__":
    unittest.main()
