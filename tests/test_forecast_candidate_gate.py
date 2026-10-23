"""Tests for the offline water-demand candidate review gate."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.evaluate_forecast_candidate import evaluate_candidate


class TestForecastCandidateGate(unittest.TestCase):
    def _write(self, path: Path, peak_risk: bool = False, invalid: str | None = None) -> None:
        start = datetime(2026, 2, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "timestamp", "actual_water_demand_m3",
                "incumbent_forecast_m3", "candidate_forecast_m3",
            ])
            writer.writeheader()
            for i in range(48):
                actual = 30.0 + (i % 8)
                incumbent = actual + 1.0
                candidate = actual + 0.2
                if peak_risk and actual >= 37:
                    candidate = actual - 5.0
                timestamp = start + timedelta(hours=i)
                if invalid == "gap" and i == 20:
                    timestamp += timedelta(hours=1)
                if invalid == "negative" and i == 10:
                    candidate = -1.0
                writer.writerow({
                    "timestamp": timestamp.isoformat(),
                    "actual_water_demand_m3": actual,
                    "incumbent_forecast_m3": incumbent,
                    "candidate_forecast_m3": candidate,
                })

    def test_recommends_candidate_only_when_overall_and_peak_checks_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "report.json"
            self._write(source)
            report = evaluate_candidate(source, output, high_demand_threshold_m3=37.0)
            self.assertEqual(report["status"], "candidate_recommended_for_review")
            self.assertTrue(report["decision_checks"]["overall_mae_check_passed"])
            self.assertTrue(report["decision_checks"]["high_demand_risk_check_passed"])
            self.assertEqual(report["row_count"], 48)
            self.assertEqual(json.loads(output.read_text())["status"], report["status"])

    def test_rejects_candidate_with_worse_high_demand_underforecasting(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "report.json"
            self._write(source, peak_risk=True)
            report = evaluate_candidate(source, output, high_demand_threshold_m3=37.0)
            self.assertEqual(report["status"], "keep_incumbent_for_now")
            self.assertTrue(report["decision_checks"]["overall_mae_check_passed"])
            self.assertFalse(report["decision_checks"]["high_demand_risk_check_passed"])

    def test_rejects_hourly_gaps_and_negative_forecasts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "report.json"
            self._write(source, invalid="gap")
            with self.assertRaisesRegex(ValueError, "continuous hourly"):
                evaluate_candidate(source, output, high_demand_threshold_m3=37.0)
            self._write(source, invalid="negative")
            with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                evaluate_candidate(source, output, high_demand_threshold_m3=37.0)

    def test_rejects_holdout_without_high_demand_events(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "report.json"
            self._write(source)
            with self.assertRaisesRegex(ValueError, "No actual observations meet"):
                evaluate_candidate(source, output, high_demand_threshold_m3=100.0)


if __name__ == "__main__":
    unittest.main()
