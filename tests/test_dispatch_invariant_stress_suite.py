"""Tests for randomized dispatch accounting invariant checks."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.run_dispatch_invariant_stress_suite import (
    main,
    run_dispatch_invariant_stress_suite,
)


class TestDispatchInvariantStressSuite(unittest.TestCase):
    def test_seeded_invariant_suite_is_deterministic_and_clean(self):
        first = run_dispatch_invariant_stress_suite(hours=4, case_count=2, seed=31)
        second = run_dispatch_invariant_stress_suite(hours=4, case_count=2, seed=31)
        self.assertEqual(first["report_sha256"], second["report_sha256"])
        self.assertEqual(first["total_case_count"], 3)
        self.assertEqual(len(first["runs"]), 3 * 4)
        self.assertGreater(first["total_invariant_checks"], 0)
        self.assertEqual(first["failed_invariant_count"], 0)
        self.assertTrue(first["all_invariants_passed"])
        self.assertFalse(first["physical_write_performed"])
        self.assertFalse(first["live_control_enabled"])
        for run in first["runs"]:
            with self.subTest(case=run["case_id"], policy=run["policy"]):
                self.assertEqual(run["failed_invariant_count"], 0)
                self.assertEqual(run["hours"], 4)
                self.assertEqual(run["invariant_checks"], 40)

    def test_cli_writes_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "invariants.json"
            code = main([
                "--hours", "3", "--cases", "1", "--seed", "5",
                "--output", str(output),
            ])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["all_invariants_passed"])
            self.assertEqual(report["total_case_count"], 2)
            self.assertEqual(len(report["report_sha256"]), 64)

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
                    run_dispatch_invariant_stress_suite(**kwargs)


if __name__ == "__main__":
    unittest.main()
