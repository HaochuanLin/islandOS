"""Tests for reproducible policy parameter sweeps without measured site data."""
import unittest

from experiments.run_policy_parameter_sweep import (
    build_parameter_sweep_cases,
    run_parameter_sweep,
)


class TestPolicyParameterSweep(unittest.TestCase):
    def test_seeded_cases_are_deterministic_and_parameterized(self):
        first = build_parameter_sweep_cases(hours=8, case_count=5, seed=17)
        second = build_parameter_sweep_cases(hours=8, case_count=5, seed=17)
        self.assertEqual(len(first), 6)  # baseline plus five randomized cases
        self.assertEqual(
            [item["factors"] for item in first],
            [item["factors"] for item in second],
        )
        self.assertEqual(first[0]["case_id"], "baseline")
        self.assertEqual(first[1]["case_id"], "seeded_001")
        self.assertNotEqual(first[1]["factors"], second[2]["factors"])

    def test_report_is_reproducible_paired_and_simulation_only(self):
        first = run_parameter_sweep(hours=6, case_count=3, seed=23)
        second = run_parameter_sweep(hours=6, case_count=3, seed=23)
        self.assertEqual(first["report_sha256"], second["report_sha256"])
        self.assertEqual(first["total_case_count"], 4)
        self.assertEqual(
            set(first["policy_summary"]),
            {"rolling", "ro_first", "ice_first", "perfect_information"},
        )
        self.assertTrue(first["all_results_simulation_only"])
        self.assertFalse(first["physical_write_performed"])
        self.assertFalse(first["live_control_enabled"])
        for case in first["cases"]:
            self.assertEqual(set(case["scores"]), set(first["policy_names"]))
            self.assertIn(case["best_fixed_policy"], {"ro_first", "ice_first"})
            self.assertIsInstance(case["rolling_constraint_violation_hours"], int)

    def test_rejects_invalid_sweep_dimensions_and_seed(self):
        for kwargs in (
            {"hours": 0, "case_count": 1, "seed": 1},
            {"hours": 2, "case_count": 0, "seed": 1},
            {"hours": 2, "case_count": 1, "seed": True},
            {"hours": 169, "case_count": 1, "seed": 1},
            {"hours": 2, "case_count": 201, "seed": 1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    build_parameter_sweep_cases(**kwargs)


if __name__ == "__main__":
    unittest.main()
