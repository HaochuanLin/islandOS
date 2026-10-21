"""Tests for objective-weight sensitivity audit."""
import unittest

from experiments.weight_sensitivity_audit import WEIGHT_SETS, summarize_weight_sensitivity


class TestWeightSensitivityAudit(unittest.TestCase):
    def test_weight_sets_are_valid(self):
        for weights in WEIGHT_SETS.values():
            self.assertEqual(len(weights), 3)
            self.assertTrue(all(weight >= 0 for weight in weights))
            self.assertAlmostEqual(sum(weights), 1.0)

    def test_audit_has_one_result_per_weight_set_and_all_cases(self):
        results = summarize_weight_sensitivity()
        self.assertEqual(len(results), len(WEIGHT_SETS))
        for result in results:
            self.assertEqual(result["case_count"], 12)
            self.assertEqual(
                result["rolling_wins"] + result["ties"] + result["rolling_losses"],
                result["case_count"],
            )
            self.assertGreaterEqual(result["max_delta"], result["min_delta"])

    def test_audit_is_reproducible(self):
        self.assertEqual(summarize_weight_sensitivity(), summarize_weight_sensitivity())


if __name__ == "__main__":
    unittest.main()
