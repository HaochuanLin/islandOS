"""Tests for common-physics flexible-load schedule evaluation."""
import unittest

from islandos_core.microgrid_model import MicrogridConfig, MicrogridInputs
from islandos_core.schedule_evaluator import evaluate_ro_schedule, rank_ro_schedules


class ScheduleEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.config = MicrogridConfig(
            battery_capacity_kwh=0, battery_initial_soc_kwh=0,
            battery_min_soc_kwh=0, battery_max_charge_kw=0,
            battery_max_discharge_kw=0, grid_import_limit_kw=0,
            diesel_capacity_kw=0, ro_rated_power_kw=20,
            ro_specific_energy_kwh_per_m3=4, water_tank_capacity_m3=20,
            water_initial_inventory_m3=0,
        )
        self.inputs = MicrogridInputs(
            pv_power_kw=[10, 30, 0], wind_power_kw=[0, 0, 0],
            essential_load_kw=[10, 10, 10], ro_requested_power_kw=[0, 0, 0],
            water_demand_m3=[0, 0, 0], grid_available=[False, False, False],
        )

    def test_all_candidates_use_same_physical_constraints(self):
        ranked = rank_ro_schedules(
            {"no_ro": [0, 0, 0], "surplus_only": [0, 20, 0]},
            self.inputs, self.config,
        )
        self.assertEqual(ranked[0].schedule_id, "surplus_only")
        self.assertTrue(ranked[0].feasible)
        self.assertEqual(ranked[0].essential_unserved_kwh, 0)
        self.assertEqual(ranked[1].essential_unserved_kwh, 0)
        self.assertGreater(ranked[0].water_produced_m3, 0)

    def test_infeasible_essential_service_is_not_hidden(self):
        scenario = MicrogridInputs(
            pv_power_kw=[0], wind_power_kw=[0], essential_load_kw=[15],
            ro_requested_power_kw=[0], water_demand_m3=[0],
            grid_available=[False],
        )
        result = evaluate_ro_schedule("no_supply", [0], scenario, self.config)
        self.assertFalse(result.feasible)
        self.assertEqual(result.essential_unserved_kwh, 15)

    def test_rejects_schedule_horizon_mismatch(self):
        with self.assertRaisesRegex(ValueError, "horizon"):
            evaluate_ro_schedule("bad", [1], self.inputs, self.config)

    def test_rejects_empty_candidate_set(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            rank_ro_schedules({}, self.inputs, self.config)


if __name__ == "__main__":
    unittest.main()
