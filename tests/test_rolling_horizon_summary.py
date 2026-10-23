"""Tests for experiment-level comparison summaries."""
import unittest

from experiments.rolling_horizon_dispatch import run_experiment, summarize_experiment


class TestRollingHorizonSummary(unittest.TestCase):
    def test_summary_has_one_row_per_scenario_error_pair(self):
        rows = summarize_experiment(run_experiment())
        self.assertEqual(len(rows), 12)
        self.assertTrue(all("rolling_score" in row for row in rows))
        self.assertTrue(all("best_fixed_score" in row for row in rows))
        self.assertTrue(all("rolling_minus_best_fixed" in row for row in rows))
        self.assertTrue(all("rolling_water_unmet_m3" in row for row in rows))
        self.assertTrue(all("best_fixed_water_unmet_m3" in row for row in rows))
        self.assertTrue(all("rolling_cooling_unmet_kwh_th" in row for row in rows))
        self.assertTrue(all("best_fixed_cooling_unmet_kwh_th" in row for row in rows))

    def test_summary_is_reproducible_and_does_not_claim_universal_winner(self):
        a = summarize_experiment(run_experiment())
        b = summarize_experiment(run_experiment())
        self.assertEqual(a, b)
        self.assertTrue(all(row["interpretation"] == "case-specific comparison; no universal winner assumed" for row in a))


if __name__ == "__main__":
    unittest.main()
