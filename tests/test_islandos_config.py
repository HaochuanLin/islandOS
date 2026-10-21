"""Tests for the shared editable parameter configuration."""
import json
import tempfile
import unittest
from pathlib import Path

from islandos_config import economics_completeness, load_config, validate_config
from experiments.compare_dispatch_policies import build_scenarios
from optimization.nsga2_dispatch_optimizer import optimize_scenario


class TestIslandOSConfig(unittest.TestCase):
    def test_default_config_is_explicit_and_valid(self):
        config = load_config()
        self.assertEqual(validate_config(config), [])
        economics = economics_completeness(config)
        self.assertFalse(economics["complete_for_current_declared_fields"])
        self.assertFalse(economics["cost_objective_implemented"])

    def test_invalid_physical_relationship_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({
                "equipment": {"ro": {"initial_water_m3": 900.0}}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "initial_water_m3"):
                load_config(path)

    def test_custom_search_space_is_used_by_optimizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.json"
            path.write_text(json.dumps({
                "metadata": {"name": "test-only configuration"},
                "search_space": {
                    "priority": ["ro_first"],
                    "ro_min_run_hours": [1],
                    "ro_start_ratio": [0.8],
                    "ro_rated_power_kw": [300.0],
                    "ice_rated_power_kw": [50.0]
                },
                "equipment": {
                    "ro": {
                        "specific_energy_kwh_m3": 4.0,
                        "reservoir_capacity_m3": 200.0,
                        "initial_water_m3": 80.0,
                        "dead_storage_m3": 10.0,
                        "allow_backup_power": False
                    },
                    "ice": {
                        "coefficient_of_performance": 2.0,
                        "storage_capacity_kwh_th": 150.0,
                        "initial_storage_kwh_th": 20.0
                    }
                }
            }), encoding="utf-8")
            config = load_config(path)
            result = optimize_scenario(
                build_scenarios()[0], population_size=4, generations=1, seed=3,
                config=config,
            )
            self.assertEqual(result["decision_space_size"], 1)
            self.assertEqual(result["unique_candidates_evaluated"], 1)
            self.assertEqual(result["parameter_config_name"], "test-only configuration")
            self.assertTrue(all(
                row["parameters"]["ro_rated_power_kw"] == 300.0
                and row["parameters"]["ice_rated_power_kw"] == 50.0
                for row in result["pareto_front"]
            ))


if __name__ == "__main__":
    unittest.main()
