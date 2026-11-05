"""Tests for the integrated energy-water physical accounting baseline."""
import unittest

import numpy as np

from islandos_core.microgrid_model import (
    MicrogridConfig, MicrogridInputs, simulate_microgrid, validate_microgrid_result,
)


class IntegratedMicrogridModelTests(unittest.TestCase):
    def config(self, **overrides):
        values = dict(
            battery_capacity_kwh=100, battery_initial_soc_kwh=50,
            battery_min_soc_kwh=10, battery_max_charge_kw=30,
            battery_max_discharge_kw=30, battery_charge_efficiency=.9,
            battery_discharge_efficiency=.9, grid_import_limit_kw=40,
            diesel_capacity_kw=50, ro_rated_power_kw=20,
            ro_specific_energy_kwh_per_m3=4, water_tank_capacity_m3=100,
            water_initial_inventory_m3=20,
        )
        values.update(overrides)
        return MicrogridConfig(**values)

    def inputs(self, **overrides):
        values = dict(
            pv_power_kw=[30, 0, 10, 0], wind_power_kw=[20, 0, 0, 0],
            essential_load_kw=[25, 35, 20, 80],
            ro_requested_power_kw=[20, 0, 10, 0],
            water_demand_m3=[2, 3, 2, 2],
            grid_available=[True, True, False, False],
            grid_price_per_kwh=[.2, .2, .2, .2],
            diesel_cost_per_kwh=.8, diesel_emissions_kg_per_kwh=.7,
        )
        values.update(overrides)
        # Keep optional time-series aligned when a test shortens the required inputs.
        n = len(values["pv_power_kw"])
        if "grid_available" not in overrides:
            values["grid_available"] = [True] * n
        if "grid_price_per_kwh" not in overrides:
            values["grid_price_per_kwh"] = [0.2] * n
        if "grid_emissions_kg_per_kwh" not in overrides:
            values["grid_emissions_kg_per_kwh"] = None
        return MicrogridInputs(**values)

    def test_allocation_and_inventory_invariants_hold(self):
        result = simulate_microgrid(self.inputs(), self.config())
        validate_microgrid_result(result, self.config())
        self.assertTrue(np.all(result.battery_soc_kwh >= 10))
        self.assertTrue(np.all(result.water_inventory_m3 >= 0))
        self.assertTrue(np.all(result.water_inventory_m3 <= 100))

    def test_essential_load_has_priority_over_ro(self):
        result = simulate_microgrid(
            self.inputs(pv_power_kw=[25], wind_power_kw=[0],
                       essential_load_kw=[35], ro_requested_power_kw=[20],
                       water_demand_m3=[0], grid_available=[False]),
            self.config(),
        )
        self.assertEqual(result.ro_power_served_kw[0], 0)
        self.assertEqual(result.unserved_essential_kw[0], 0)
        self.assertEqual(result.battery_discharge_kw[0], 10)

    def test_ro_uses_only_renewable_surplus_after_essential_load(self):
        result = simulate_microgrid(
            self.inputs(pv_power_kw=[50], wind_power_kw=[0],
                       essential_load_kw=[25], ro_requested_power_kw=[20],
                       water_demand_m3=[0]),
            self.config(),
        )
        self.assertEqual(result.ro_power_served_kw[0], 20)
        # The remaining 5 kW is charged into the battery before curtailment.
        self.assertEqual(result.battery_charge_kw[0], 5)
        self.assertEqual(result.renewable_curtailed_kw[0], 0)

    def test_battery_charges_from_remaining_renewables(self):
        result = simulate_microgrid(
            self.inputs(pv_power_kw=[80], wind_power_kw=[0],
                       essential_load_kw=[20], ro_requested_power_kw=[0],
                       water_demand_m3=[0]),
            self.config(battery_initial_soc_kwh=0, battery_min_soc_kwh=0),
        )
        self.assertEqual(result.battery_charge_kw[0], 30)
        self.assertEqual(result.renewable_curtailed_kw[0], 30)
        self.assertAlmostEqual(result.battery_soc_kwh[1], 27)

    def test_water_production_respects_tank_headroom(self):
        result = simulate_microgrid(
            self.inputs(pv_power_kw=[100], wind_power_kw=[0],
                       essential_load_kw=[0], ro_requested_power_kw=[20],
                       water_demand_m3=[0]),
            self.config(water_initial_inventory_m3=99),
        )
        self.assertAlmostEqual(result.water_produced_m3[0], 1)
        self.assertAlmostEqual(result.ro_power_served_kw[0], 4)
        self.assertAlmostEqual(result.water_inventory_m3[1], 100)

    def test_grid_and_diesel_limits_and_unserved_load_are_explicit(self):
        result = simulate_microgrid(
            self.inputs(pv_power_kw=[0], wind_power_kw=[0],
                       essential_load_kw=[150], ro_requested_power_kw=[0],
                       water_demand_m3=[0], grid_available=[True]),
            self.config(battery_initial_soc_kwh=10, battery_min_soc_kwh=10,
                        grid_import_limit_kw=20, diesel_capacity_kw=30),
        )
        self.assertEqual(result.grid_import_kw[0], 20)
        self.assertEqual(result.diesel_generation_kw[0], 30)
        self.assertEqual(result.unserved_essential_kw[0], 100)

    def test_grid_outage_uses_diesel_after_battery(self):
        result = simulate_microgrid(
            self.inputs(pv_power_kw=[0], wind_power_kw=[0],
                       essential_load_kw=[50], ro_requested_power_kw=[0],
                       water_demand_m3=[0], grid_available=[False]),
            self.config(battery_initial_soc_kwh=10, battery_min_soc_kwh=10,
                        diesel_capacity_kw=20),
        )
        self.assertEqual(result.grid_import_kw[0], 0)
        self.assertEqual(result.diesel_generation_kw[0], 20)
        self.assertEqual(result.unserved_essential_kw[0], 30)

    def test_input_lengths_and_nonfinite_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "equal lengths"):
            simulate_microgrid(self.inputs(wind_power_kw=[0]), self.config())
        with self.assertRaisesRegex(ValueError, "finite"):
            simulate_microgrid(self.inputs(pv_power_kw=[float("nan")]), self.config())

    def test_infeasible_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "battery SOC"):
            simulate_microgrid(self.inputs(), self.config(
                battery_initial_soc_kwh=5, battery_min_soc_kwh=10,
            ))
        with self.assertRaisesRegex(ValueError, "RO rating"):
            simulate_microgrid(self.inputs(), self.config(ro_rated_power_kw=0))


if __name__ == "__main__":
    unittest.main()
