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

    def test_ro_initial_run_commitment_is_carried_into_next_call(self):
        ro = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=2,
            initial_water_m3=500, dead_storage_m3=0,
            reservoir_capacity_m3=1000, min_run_hours=2,
            allow_backup_power=False,
        ))
        result = ro.simulate(
            [0], [0], initial_run_hours_remaining=1,
        )
        # The unit is still committed, but the missing renewable power is
        # surfaced as a violation rather than silently cancelling the run.
        self.assertEqual(result.active.tolist(), [1])
        self.assertEqual(result.constraint_violation.tolist(), [1])
        self.assertEqual(result.run_hours_remaining, 0)

    def test_ro_rejects_invalid_initial_run_commitment(self):
        ro = ROWaterLoad(ROConfig(min_run_hours=2))
        for invalid in (-1, 3, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "initial_run_hours_remaining"):
                    ro.simulate([0], [0], initial_run_hours_remaining=invalid)

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

    def test_ro_does_not_start_a_minimum_run_that_cannot_finish(self):
        ro = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=2,
            initial_water_m3=500, dead_storage_m3=0,
            reservoir_capacity_m3=1000, min_run_hours=2,
            allow_backup_power=True, start_ratio=0.5,
        ))
        result = ro.simulate([0, 100, 100], [0, 0, 0])
        # t=0 has no power; t=1 has exactly two hours remaining and may start.
        self.assertEqual(result.active.tolist(), [0, 1, 1])
        one_hour_left = ro.simulate([100], [0])
        self.assertEqual(one_hour_left.active.tolist(), [0])
        self.assertEqual(int(one_hour_left.constraint_violation.sum()), 0)

    def test_ro_water_inventory_balance_each_step(self):
        ro = ROWaterLoad(ROConfig(
            rated_power_kw=100, specific_energy_kwh_m3=2,
            initial_water_m3=50, dead_storage_m3=5,
            reservoir_capacity_m3=60, min_run_hours=1,
            allow_backup_power=True, start_ratio=0.5,
        ))
        result = ro.simulate([100, 100, 0], [10, 10, 10])
        for t in range(3):
            expected = (
                result.inventory[t] + result.resource_produced[t]
                - result.spill[t] - result.demand_served[t]
            )
            self.assertAlmostEqual(result.inventory[t + 1], expected)
            self.assertAlmostEqual(
                result.demand_served[t] + result.unmet_demand[t], 10
            )
        self.assertTrue(np.all(result.inventory <= 60 + 1e-9))
        self.assertTrue(np.all(result.inventory >= 5 - 1e-9))

    def test_ice_inventory_balance_each_step(self):
        ice = IceStorageLoad(IceStorageConfig(
            rated_power_kw=50, coefficient_of_performance=2,
            storage_capacity_kwh_th=150, initial_storage_kwh_th=20,
        ))
        demand = [0, 30, 60, 10]
        result = ice.simulate([50, 0, 50, 0], demand)
        for t in range(len(demand)):
            self.assertAlmostEqual(
                result.inventory[t + 1],
                result.inventory[t] + result.resource_produced[t]
                - result.demand_served[t] - result.spill[t],
            )
            self.assertAlmostEqual(
                result.demand_served[t] + result.unmet_demand[t], demand[t]
            )
        self.assertTrue(np.all(result.inventory >= -1e-9))
        self.assertTrue(np.all(result.inventory <= 150 + 1e-9))

    def test_invalid_ro_start_ratio_is_rejected(self):
        ro = ROWaterLoad(ROConfig(start_ratio=1.1))
        with self.assertRaisesRegex(ValueError, "start_ratio"):
            ro.simulate([500], [0])

    def test_non_finite_ro_configuration_is_rejected(self):
        for config in (
            ROConfig(reservoir_capacity_m3=float("inf")),
            ROConfig(initial_water_m3=float("nan")),
            ROConfig(dead_storage_m3=float("inf")),
        ):
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, "configuration values must be finite"):
                    ROWaterLoad(config).simulate([0], [0])

    def test_non_finite_ice_configuration_is_rejected(self):
        for config in (
            IceStorageConfig(coefficient_of_performance=float("nan")),
            IceStorageConfig(storage_capacity_kwh_th=float("inf")),
            IceStorageConfig(initial_storage_kwh_th=float("nan")),
        ):
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, "configuration values must be finite"):
                    IceStorageLoad(config).simulate([0], [0])

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
