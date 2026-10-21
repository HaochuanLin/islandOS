"""Regression tests for shared-budget flexible-load dispatch."""
import unittest

import numpy as np

from dispatch_engine import dispatch_flexible_loads
from flexible_loads import (
    IceStorageConfig, IceStorageLoad, LoadSimulationResult,
    ROConfig, ROWaterLoad,
)


class TestSharedBudgetDispatch(unittest.TestCase):
    def _ro(self, backup=False):
        return ROWaterLoad(ROConfig(
            rated_power_kw=100,
            specific_energy_kwh_m3=2,
            reservoir_capacity_m3=1000,
            initial_water_m3=500,
            dead_storage_m3=0,
            min_run_hours=1,
            start_ratio=0.5,
            allow_backup_power=backup,
        ))

    def _ice(self):
        return IceStorageLoad(IceStorageConfig(
            rated_power_kw=100,
            coefficient_of_performance=2,
            storage_capacity_kwh_th=500,
            initial_storage_kwh_th=0,
        ))

    def test_priority_order_prevents_double_allocation(self):
        available = [150, 150]
        ice_first = dispatch_flexible_loads(
            available,
            [(self._ice(), [0, 0]), (self._ro(), [0, 0])],
        )
        self.assertTrue(np.allclose(ice_first.loads["ice_cold_storage"].power_used_kw, [100, 100]))
        self.assertTrue(np.allclose(ice_first.loads["ro_desalination"].power_used_kw, [0, 0]))
        self.assertTrue(np.allclose(ice_first.remaining_power_kw, [50, 50]))

        ro_first = dispatch_flexible_loads(
            available,
            [(self._ro(), [0, 0]), (self._ice(), [0, 0])],
        )
        self.assertTrue(np.allclose(ro_first.loads["ro_desalination"].power_used_kw, [100, 100]))
        self.assertTrue(np.allclose(ro_first.loads["ice_cold_storage"].power_used_kw, [50, 50]))
        self.assertTrue(np.allclose(ro_first.remaining_power_kw, [0, 0]))

    def test_power_budget_conservation(self):
        result = dispatch_flexible_loads(
            [150, 70, 0],
            [(self._ro(), [0, 0, 0]), (self._ice(), [0, 0, 0])],
        )
        self.assertTrue(np.all(result.renewable_power_used_kw <= result.initial_available_power_kw + 1e-9))
        self.assertTrue(np.allclose(
            result.initial_available_power_kw,
            result.renewable_power_used_kw + result.remaining_power_kw,
        ))
        self.assertTrue(np.all(result.remaining_power_kw >= 0))

    def test_backup_is_separate_from_renewable_budget(self):
        result = dispatch_flexible_loads(
            [60, 60],
            [(self._ro(backup=True), [0, 0])],
        )
        ro = result.loads["ro_desalination"]
        self.assertTrue(np.allclose(ro.power_used_kw, [100, 100]))
        self.assertTrue(np.allclose(ro.backup_power_kw, [40, 40]))
        self.assertTrue(np.allclose(result.renewable_power_used_kw, [60, 60]))
        self.assertTrue(np.allclose(result.remaining_power_kw, [0, 0]))
        self.assertTrue(np.allclose(result.backup_power_kw, [40, 40]))

    def test_plugin_inventory_conservation_violation_is_rejected(self):
        class BrokenLoad:
            name = "broken_inventory"

            def simulate(self, available_power_kw, demand, dt_hours=1.0):
                return LoadSimulationResult(
                    power_used_kw=np.array([0.0]),
                    backup_power_kw=np.array([0.0]),
                    constraint_violation=np.array([0]),
                    resource_produced=np.array([0.0]),
                    demand_served=np.array([0.0]),
                    unmet_demand=np.array([0.0]),
                    spill=np.array([0.0]),
                    active=np.array([0]),
                    inventory=np.array([0.0, 1.0]),
                )

        with self.assertRaisesRegex(RuntimeError, "inventory conservation"):
            dispatch_flexible_loads([0], [(BrokenLoad(), [0])])

    def test_plugin_demand_balance_violation_is_rejected(self):
        class BrokenLoad:
            name = "broken_demand"

            def simulate(self, available_power_kw, demand, dt_hours=1.0):
                return LoadSimulationResult(
                    power_used_kw=np.array([0.0]),
                    backup_power_kw=np.array([0.0]),
                    constraint_violation=np.array([0]),
                    resource_produced=np.array([0.0]),
                    demand_served=np.array([0.0]),
                    unmet_demand=np.array([0.0]),
                    spill=np.array([0.0]),
                    active=np.array([0]),
                    inventory=np.array([0.0, 0.0]),
                )

        with self.assertRaisesRegex(RuntimeError, "demand served"):
            dispatch_flexible_loads([0], [(BrokenLoad(), [1])])

    def test_duplicate_names_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate load name"):
            dispatch_flexible_loads(
                [100], [(self._ice(), [0]), (self._ice(), [0])]
            )

    def test_mismatched_series_rejected(self):
        with self.assertRaisesRegex(ValueError, "must match"):
            dispatch_flexible_loads([100, 100], [(self._ice(), [0])])

    def test_invalid_available_power_rejected(self):
        with self.assertRaises(ValueError):
            dispatch_flexible_loads([100, -1], [])


if __name__ == "__main__":
    unittest.main()
