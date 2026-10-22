import unittest

import numpy as np

from island_microgrid_ro_sim import Params, simulate, check_min_run


class SimulationInvariantTests(unittest.TestCase):
    def setUp(self):
        self.wind = np.array([500.0, 700.0, 0.0, 900.0])
        self.pv = np.array([0.0, 100.0, 0.0, 0.0])
        self.load = np.array([200.0, 200.0, 200.0, 200.0])
        self.demand = np.array([10.0, 12.0, 15.0, 8.0])

    def test_hourly_water_balance_and_storage_bounds(self):
        p = Params(
            ro_power_kw=300.0,
            ro_sec_kwh_m3=3.0,
            min_run_hours=2,
            allow_backup_power=True,
            res_capacity_m3=100.0,
            res_init_m3=30.0,
            res_min_m3=10.0,
            res_area_m2=100.0,
        )
        result = simulate(self.wind, self.pv, self.load, self.demand, p)
        raw_balance = (
            result["V"][:-1]
            + result["water_prod"]
            - self.demand
            - result["spill"]
            + result["deficit"]
        )
        np.testing.assert_allclose(result["V"][1:], raw_balance)
        self.assertTrue(np.all(result["V"] >= p.res_min_m3))
        self.assertTrue(np.all(result["V"] <= p.res_capacity_m3))
        self.assertTrue(np.all(result["spill"] >= 0))
        self.assertTrue(np.all(result["deficit"] >= 0))

    def test_backup_energy_closes_ro_power_balance(self):
        p = Params(
            ro_power_kw=300.0,
            ro_sec_kwh_m3=3.0,
            min_run_hours=2,
            allow_backup_power=True,
            res_capacity_m3=500.0,
            res_init_m3=100.0,
            res_min_m3=10.0,
        )
        result = simulate(self.wind, self.pv, self.load, self.demand, p)
        np.testing.assert_allclose(
            result["ro_use"] + result["ro_backup"],
            result["ro_on"] * p.ro_power_kw,
        )

    def test_mismatched_input_lengths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "equal lengths"):
            simulate(self.wind, self.pv, self.load[:-1], self.demand, Params())

    def test_negative_and_nonfinite_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "negative"):
            simulate([-1.0], [0.0], [0.0], [1.0], Params())
        with self.assertRaisesRegex(ValueError, "finite"):
            simulate([np.nan], [0.0], [0.0], [1.0], Params())

    def test_empty_and_multidimensional_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            simulate([], [], [], [], Params())
        with self.assertRaisesRegex(ValueError, "one-dimensional"):
            simulate([[1.0]], [0.0], [0.0], [1.0], Params())

    def test_invalid_reservoir_and_ro_parameters_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "ro_sec_kwh_m3"):
            simulate([1.0], [0.0], [0.0], [1.0], Params(ro_sec_kwh_m3=0.0))
        with self.assertRaisesRegex(ValueError, "res_init_m3"):
            simulate([1.0], [0.0], [0.0], [1.0], Params(
                res_capacity_m3=100.0, res_init_m3=101.0, res_min_m3=10.0
            ))

    def test_no_backup_dispatch_never_runs_below_rated_power(self):
        p = Params(
            ro_power_kw=300.0,
            ro_sec_kwh_m3=3.0,
            min_run_hours=2,
            allow_backup_power=False,
            res_capacity_m3=1000.0,
            res_init_m3=100.0,
            res_min_m3=0.0,
        )
        result = simulate(
            [500.0, 500.0, 100.0, 500.0, 500.0],
            [0.0] * 5,
            [0.0] * 5,
            [0.0] * 5,
            p,
        )
        self.assertTrue(np.all(result["ro_on"][result["curtail"] < p.ro_power_kw] == 0))
        segments, ok = check_min_run(result["ro_on"], p.min_run_hours)
        self.assertEqual(segments, [2, 2])
        self.assertTrue(ok)
        self.assertEqual(float(result["ro_backup"].sum()), 0.0)

    def test_dispatch_avoids_discretionary_overflow(self):
        p = Params(
            ro_power_kw=300.0,
            ro_sec_kwh_m3=3.0,
            min_run_hours=2,
            allow_backup_power=True,
            res_capacity_m3=100.0,
            res_init_m3=90.0,
            res_min_m3=0.0,
        )
        result = simulate(
            [1000.0, 1000.0, 1000.0],
            [0.0] * 3,
            [0.0] * 3,
            [0.0] * 3,
            p,
        )
        self.assertEqual(int(result["ro_on"].sum()), 0)
        self.assertEqual(float(result["spill"].sum()), 0.0)

    def test_full_reservoir_can_still_run_if_demand_creates_room(self):
        p = Params(
            ro_power_kw=300.0,
            ro_sec_kwh_m3=3.0,
            min_run_hours=2,
            allow_backup_power=True,
            res_capacity_m3=100.0,
            res_init_m3=100.0,
            res_min_m3=0.0,
        )
        result = simulate(
            [500.0, 500.0],
            [0.0, 0.0],
            [0.0, 0.0],
            [150.0, 150.0],
            p,
        )
        self.assertEqual(result["ro_on"].tolist(), [1, 1])
        self.assertEqual(float(result["spill"].sum()), 0.0)

    def test_minimum_run_checker_counts_horizon_truncation(self):
        segments, ok = check_min_run(np.array([0, 1, 1, 1, 0, 1]), 2)
        self.assertEqual(segments, [3, 1])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
