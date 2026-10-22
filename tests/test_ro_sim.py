"""Regression tests for the RO/reservoir co-simulation.

Run from the repository root:
    python -m unittest discover -s tests -v
"""
import unittest

import numpy as np

from island_microgrid_ro_sim import Params, simulate, check_min_run


def run_case(curtail, demand=None, params=None):
    curtail = np.asarray(curtail, dtype=float)
    # Construct renewable input so the desired curtailment is reproduced exactly.
    zeros = np.zeros_like(curtail)
    load = zeros.copy()
    wind = curtail.copy()
    pv = zeros.copy()
    if demand is None:
        demand = zeros.copy()
    if params is None:
        params = Params()
    return simulate(wind, pv, load, np.asarray(demand, dtype=float), params)


class TestROSimulation(unittest.TestCase):
    def test_no_backup_never_starts_into_infeasible_minimum_run_window(self):
        p = Params(ro_power_kw=100, min_run_hours=3, start_ratio=0.5,
                   allow_backup_power=False, res_capacity_m3=10000,
                   res_init_m3=1000, res_min_m3=0)
        # Mean is high enough to fool the old rule, but the second hour is insufficient.
        result = run_case([100, 20, 100, 100, 100, 100], params=p)
        self.assertEqual(int(result["emergency_stop"].sum()), 0)
        _, ok = check_min_run(result["ro_on"], p.min_run_hours)
        self.assertTrue(ok)
        self.assertEqual(result["ro_backup"].sum(), 0)

    def test_no_backup_runs_only_when_every_minimum_run_hour_is_feasible(self):
        p = Params(ro_power_kw=100, min_run_hours=2, allow_backup_power=False,
                   res_capacity_m3=10000, res_init_m3=1000, res_min_m3=0)
        result = run_case([100, 100, 100, 100], params=p)
        runs, ok = check_min_run(result["ro_on"], p.min_run_hours)
        self.assertTrue(ok)
        self.assertTrue(all(n >= p.min_run_hours for n in runs))
        self.assertEqual(int(result["emergency_stop"].sum()), 0)

    def test_backup_power_covers_forced_run_shortfall(self):
        p = Params(ro_power_kw=100, min_run_hours=2, start_ratio=0.8,
                   allow_backup_power=True, res_capacity_m3=10000,
                   res_init_m3=1000, res_min_m3=0)
        result = run_case([100, 60, 60, 0], params=p)
        # Once started, the second hour is kept running and the shortfall is backed up.
        self.assertEqual(result["ro_on"][0], 1)
        self.assertEqual(result["ro_on"][1], 1)
        self.assertAlmostEqual(result["ro_backup"][1], 40.0)

    def test_no_start_when_minimum_run_does_not_fit_horizon(self):
        p = Params(ro_power_kw=100, min_run_hours=3, allow_backup_power=True,
                   res_capacity_m3=10000, res_init_m3=1000, res_min_m3=0)
        result = run_case([200, 200], params=p)
        self.assertEqual(int(result["ro_on"].sum()), 0)

    def test_dispatch_avoids_overflow_and_preserves_reservoir_bounds(self):
        p = Params(ro_power_kw=100, ro_sec_kwh_m3=1, min_run_hours=1,
                   start_ratio=0.1, allow_backup_power=True,
                   res_capacity_m3=120, res_init_m3=110, res_min_m3=20)
        # Starting the RO plant would add 100 m3 with no demand, exceeding capacity.
        # The look-ahead dispatch should therefore leave the plant off.
        result = run_case([100, 100], demand=[0, 0], params=p)
        self.assertEqual(int(result["ro_on"].sum()), 0)
        self.assertTrue(np.all(result["V"] <= p.res_capacity_m3))
        self.assertTrue(np.all(result["V"] >= p.res_min_m3))
        self.assertEqual(float(result["spill"].sum()), 0.0)
        np.testing.assert_allclose(result["V"], [110.0, 110.0, 110.0])

    def test_input_length_mismatch_fails_clearly(self):
        p = Params()
        with self.assertRaises((ValueError, IndexError)):
            simulate(np.zeros(3), np.zeros(3), np.zeros(2), np.zeros(3), p)


if __name__ == "__main__":
    unittest.main()
