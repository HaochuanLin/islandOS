"""Tests for the synthetic baseline-versus-coordinated impact scenario."""
import json
import unittest
from pathlib import Path
import tempfile

import numpy as np

from islandos_core.impact_scenario import (
    IslandSiteConfig, StrategyRules, compare, generate_synthetic_inputs, run_strategy,
)


class ImpactScenarioTests(unittest.TestCase):
    def setUp(self):
        self.site = IslandSiteConfig()
        self.inputs = generate_synthetic_inputs(self.site, days=3, seed=4)

    def test_inputs_are_reproducible(self):
        again = generate_synthetic_inputs(self.site, days=3, seed=4)
        self.assertEqual(self.inputs.sha256(), again.sha256())
        other = generate_synthetic_inputs(self.site, days=3, seed=5)
        self.assertNotEqual(self.inputs.sha256(), other.sha256())

    def test_daily_water_demand_matches_config(self):
        per_day = self.inputs.water_demand_m3.sum() / 3
        self.assertAlmostEqual(per_day, self.site.daily_water_demand_m3, delta=0.05 * self.site.daily_water_demand_m3)

    def test_water_balance_closes(self):
        for name in ("baseline", "coordinated"):
            h = run_strategy(name, self.inputs, self.site).hourly
            opening = np.concatenate([[self.site.tank_initial_m3], h["tank_m3"][:-1]])
            np.testing.assert_allclose(opening + h["water_produced_m3"] - h["water_served_m3"], h["tank_m3"], atol=1e-9)
            self.assertTrue(np.all(h["tank_m3"] <= self.site.tank_capacity_m3 + 1e-9))
            self.assertTrue(np.all(h["tank_m3"] >= -1e-9))

    def test_limits_are_respected(self):
        for name in ("baseline", "coordinated"):
            h = run_strategy(name, self.inputs, self.site).hourly
            self.assertTrue(np.all(h["ro_power_kw"] <= self.site.ro_rated_power_kw + 1e-9))
            self.assertTrue(np.all(h["diesel_kw"] <= self.site.diesel_capacity_kw + 1e-9))
            self.assertTrue(np.all(h["soc_kwh"] >= self.site.battery_min_soc_kwh - 1e-9))
            self.assertTrue(np.all(h["soc_kwh"] <= self.site.battery_capacity_kwh + 1e-9))

    def test_surplus_ro_only_uses_leftover_renewables(self):
        # With the reserve threshold set to zero, coordinated RO never runs as a firm load.
        rules = StrategyRules(coordinated_reserve_fraction=0.0)
        h = run_strategy("coordinated", self.inputs, self.site, rules).hourly
        self.assertEqual(h["ro_mode_firm"].sum(), 0)
        leftover = np.clip(self.inputs.pv_kw + self.inputs.wind_kw - self.inputs.essential_kw, 0, None)
        self.assertTrue(np.all(h["ro_power_kw"] <= leftover + 1e-9))

    def test_ro_respects_minimum_power(self):
        for name in ("baseline", "coordinated"):
            h = run_strategy(name, self.inputs, self.site).hourly
            running = h["ro_power_kw"][h["ro_power_kw"] > 1e-9]
            self.assertTrue(np.all(running >= self.site.ro_min_power_kw - 1e-9))

    def test_brine_follows_recovery_ratio(self):
        s = run_strategy("coordinated", self.inputs, self.site).summary
        expected = s["water_produced_m3"] * (1 / self.site.ro_recovery_ratio - 1)
        self.assertAlmostEqual(s["brine_m3"], expected)

    def test_compare_uses_identical_inputs(self):
        result = compare(self.inputs, self.site)
        self.assertEqual(result["input_sha256"], self.inputs.sha256())
        self.assertAlmostEqual(
            result["baseline"].summary["renewable_available_kwh"],
            result["coordinated"].summary["renewable_available_kwh"],
        )

    def test_unknown_strategy_rejected(self):
        with self.assertRaises(ValueError):
            run_strategy("magic", self.inputs, self.site)

    def test_runner_writes_reproducibility_files(self):
        from experiments.run_impact_scenario import main
        with tempfile.TemporaryDirectory() as tmp:
            main(["--seeds", "2", "--days", "2", "--output-dir", tmp])
            for name in ("manifest.json", "per_seed_summary.csv", "aggregate.json", "hourly_seed0.csv", "summary.md"):
                self.assertTrue((Path(tmp) / name).exists(), name)
            manifest = json.loads((Path(tmp) / "manifest.json").read_text())
            self.assertEqual(manifest["seeds"], [0, 1])
            self.assertIn("assumptions", manifest)


if __name__ == "__main__":
    unittest.main()
