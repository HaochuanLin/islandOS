"""Tests for the experiments NSGA-II dispatch optimizer."""
import unittest

import numpy as np

from experiments.compare_energy_water_strategies import Config, SiteStep
from experiments.nsga2_dispatch_optimizer import (
    POWER_LEVELS_KW,
    _decode_power_levels,
    _evaluate_schedule,
    _objective_vector,
    optimize_dispatch,
)


def make_steps(count=4, *, surplus=10.0, demand=0.0, price=0.2, off_peak=True):
    return [
        SiteStep(
            timestamp=f"2026-01-01T{hour:02d}:00:00",
            renewable_surplus_kw=surplus,
            diesel_displacement_potential_kw=0.0,
            grid_price_per_kwh=price,
            off_peak=off_peak,
            grid_available=True,
            water_demand_m3=demand,
        )
        for hour in range(count)
    ]


def make_config(*, tank=100.0, initial=0.0, min_run=1, dt=1.0):
    return Config(
        ro_rated_power_kw=10.0,
        specific_energy_kwh_m3=4.0,
        tank_capacity_m3=tank,
        initial_water_m3=initial,
        min_run_hours=min_run,
        dt_hours=dt,
    )


class TestNSGA2DispatchOptimizer(unittest.TestCase):
    def test_power_level_encoding_is_one_gene_per_step(self):
        self.assertEqual(POWER_LEVELS_KW, (0.0, 6.0, 8.0, 10.0))
        self.assertEqual(
            _decode_power_levels(np.array([0, 1, 2, 3]), 4),
            [0.0, 6.0, 8.0, 10.0],
        )

    def test_decoder_rejects_wrong_length_and_invalid_levels(self):
        with self.assertRaisesRegex(ValueError, "length"):
            _decode_power_levels(np.array([0, 1]), 3)
        with self.assertRaisesRegex(ValueError, "index"):
            _decode_power_levels(np.array([0, 4]), 2)

    def test_objectives_are_only_grid_cost_and_ro_starts(self):
        summary = {
            "grid_energy_cost": 12.5,
            "ro_switch_on_count": 3,
            "surplus_energy_to_ro_kwh": 99.0,
            "grid_peak_power_kw": 10.0,
        }
        self.assertEqual(_objective_vector(summary), (12.5, 3.0))

    def test_surplus_dispatch_accounts_energy_without_grid_cost(self):
        summary, details = _evaluate_schedule(np.array([3, 0, 3, 0]), make_steps(), make_config())
        self.assertEqual(summary["grid_energy_cost"], 0.0)
        self.assertEqual(summary["surplus_energy_to_ro_kwh"], 20.0)
        self.assertEqual(summary["ro_switch_on_count"], 2)
        self.assertEqual(len(details), 4)

    def test_optimizer_returns_feasible_nondominated_schedules(self):
        # A tiny horizon keeps this integration test quick while exercising the
        # actual 120-member / 60-generation optimizer configuration.
        steps = make_steps(count=4, surplus=0.0, demand=1.0, price=0.01, off_peak=True)
        config = make_config(tank=100.0)
        summaries, schedules, meta = optimize_dispatch(
            steps, config, population_size=120, generations=60, seed=42
        )
        self.assertGreater(meta["evaluations"], 0)
        self.assertEqual(meta["objective_count"], 2)
        self.assertEqual(meta["gene_count"], len(steps))
        for summary in summaries:
            self.assertLessEqual(summary["unmet_water_demand_m3"], 1e-6)
            self.assertEqual(summary["minimum_run_constraint_violations"], 0)
            self.assertLessEqual(summary["water_spill_m3"], 1e-6)
            self.assertGreaterEqual(summary["ending_water_inventory_m3"], -1e-6)
            self.assertLessEqual(summary["ending_water_inventory_m3"], config.tank_capacity_m3 + 1e-6)
        if summaries:
            self.assertTrue(schedules)
            self.assertEqual(
                len({row["strategy"] for row in schedules}),
                len(summaries),
            )

    def test_optimizer_returns_no_feasible_result_when_demand_is_impossible(self):
        # A tiny tank and extreme demand make zero unmet water mathematically
        # impossible regardless of the chosen RO schedule.
        steps = make_steps(count=4, surplus=10.0, demand=1000.0, off_peak=True)
        config = make_config(tank=0.1, initial=0.0)
        summaries, schedules, meta = optimize_dispatch(
            steps, config, population_size=120, generations=60, seed=42
        )
        self.assertEqual(summaries, [])
        self.assertEqual(schedules, [])
        self.assertEqual(meta["feasible_count"], 0)
        self.assertGreater(meta["evaluations"], 0)

    def test_optimizer_rejects_population_below_configured_minimum(self):
        with self.assertRaisesRegex(ValueError, "population_size"):
            optimize_dispatch(make_steps(), make_config(), population_size=20, generations=60)


if __name__ == "__main__":
    unittest.main()
