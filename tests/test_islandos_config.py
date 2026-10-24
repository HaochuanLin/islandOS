"""Tests for the shared editable parameter configuration."""
import json
import tempfile
import unittest
from pathlib import Path

from islandos_config import economics_completeness, load_config, validate_config
from flexible_loads import IceStorageConfig, ROConfig
from experiments.compare_dispatch_policies import build_scenarios
from optimization.nsga2_dispatch_optimizer import optimize_scenario


class TestIslandOSConfig(unittest.TestCase):
    def test_default_config_is_explicit_and_valid(self):
        config = load_config()
        self.assertEqual(validate_config(config), [])
        economics = economics_completeness(config)
        self.assertFalse(economics["complete_for_current_declared_fields"])
        self.assertFalse(economics["cost_objective_implemented"])

    def test_low_level_load_defaults_match_shared_config(self):
        config = load_config()
        ro = ROConfig()
        ice = IceStorageConfig()
        self.assertEqual(ro.specific_energy_kwh_m3, config["equipment"]["ro"]["specific_energy_kwh_m3"])
        self.assertEqual(ro.reservoir_capacity_m3, config["equipment"]["ro"]["reservoir_capacity_m3"])
        self.assertEqual(ro.initial_water_m3, config["equipment"]["ro"]["initial_water_m3"])
        self.assertEqual(ro.dead_storage_m3, config["equipment"]["ro"]["dead_storage_m3"])
        self.assertEqual(ro.allow_backup_power, config["equipment"]["ro"]["allow_backup_power"])
        self.assertEqual(ice.coefficient_of_performance, config["equipment"]["ice"]["coefficient_of_performance"])
        self.assertEqual(ice.storage_capacity_kwh_th, config["equipment"]["ice"]["storage_capacity_kwh_th"])
        self.assertEqual(ice.initial_storage_kwh_th, config["equipment"]["ice"]["initial_storage_kwh_th"])

    def test_invalid_physical_relationship_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({
                "equipment": {"ro": {"initial_water_m3": 900.0}}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "initial_water_m3"):
                load_config(path)

    def test_metadata_and_provenance_policy_must_be_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                ({"metadata": None}, "metadata must be an object"),
                ({"metadata": {"name": None}}, "metadata.name must be a non-empty string"),
                ({"metadata": {"status": " "}}, "metadata.status must be a non-empty string"),
                ({"metadata": {"notes": 12}}, "metadata.notes must be a string"),
                ({"parameter_sources": None}, "parameter_sources must be an object"),
                ({"parameter_sources": {"default_policy": ""}}, "default_policy must be a non-empty string"),
            ]
            for index, (override, message) in enumerate(cases):
                path = Path(tmp) / f"bad-metadata-{index}.json"
                path.write_text(json.dumps(override), encoding="utf-8")
                with self.subTest(override=override):
                    with self.assertRaisesRegex(ValueError, message):
                        load_config(path)

    def test_boolean_config_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "boolean-version.json"
            path.write_text(json.dumps({"config_version": True}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "config_version must be 1"):
                load_config(path)

    def test_inactive_start_ratio_is_removed_from_default_search(self):
        config = load_config()
        result = optimize_scenario(
            build_scenarios()[0], population_size=4, generations=1, seed=3,
            config=config,
        )
        self.assertEqual(result["decision_space_size"], 96)
        self.assertEqual(result["effective_search_space"]["ro_start_ratio"], [0.6])
        self.assertTrue(result["inactive_parameters"])

    def test_misspelled_parameter_is_rejected_instead_of_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "typo.json"
            path.write_text(json.dumps({
                "equipment": {"ro": {"specific_energy_kwh_m3_typo": 9.9}}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown configuration key"):
                load_config(path)

    def test_duplicate_search_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicates.json"
            path.write_text(json.dumps({
                "search_space": {"ro_rated_power_kw": [300.0, 300.0]}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique values"):
                load_config(path)

    def test_empty_cost_currency_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-currency.json"
            path.write_text(json.dumps({
                "economics": {"currency": " "}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "currency label"):
                load_config(path)

    def test_invalid_analysis_horizon_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-years.json"
            path.write_text(json.dumps({
                "economics": {"analysis_years": 20.5}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "positive integer"):
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
