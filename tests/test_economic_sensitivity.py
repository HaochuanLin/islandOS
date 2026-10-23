"""Tests for the fixed-candidate economic sensitivity report."""
import json
import tempfile
import unittest
from pathlib import Path

from experiments.economic_sensitivity import _annual_cost, run_economic_sensitivity


def make_report(electricity_price=0.12):
    economics = {
        "currency": "USD",
        "electricity_price_per_kwh": electricity_price,
        "ro_capex": 100000.0,
        "ro_fixed_om_per_year": 5000.0,
        "ro_variable_om_per_m3": 0.2,
        "chiller_capex": 20000.0,
        "chiller_fixed_om_per_year": 1000.0,
        "analysis_years": 15,
        "discount_rate": 0.08,
        "source_notes": "Synthetic test fixture only",
    }
    candidates = []
    for index, (energy, water, power) in enumerate(((10000.0, 5000.0, 300.0), (8000.0, 4000.0, 250.0))):
        breakdown = {
            "annual_energy_used_by_flexible_loads_kwh": energy,
            "annual_water_produced_m3": water,
        }
        candidates.append({
            "parameters": {
                "priority": "ro_first" if index == 0 else "ice_first",
                "ro_rated_power_kw": power,
                "ice_rated_power_kw": 75.0,
            },
            "cost_breakdown": breakdown,
            "objectives": {
                "annualized_lifecycle_cost_per_year": _annual_cost(breakdown, economics)
            },
        })
    return {
        "input_summary": {
            "quality_status": "valid",
            "source_type": "synthetic",
            "row_count": 8760,
            "interval_minutes": 60,
            "first_timestamp": "2026-01-01T00:00:00Z",
            "last_timestamp": "2026-12-31T23:00:00Z",
        },
        "data_quality_report": {"status": "valid", "issues": []},
        "parameter_configuration": {
            "economics": economics,
            "economics_completeness": {"complete_for_current_declared_fields": True},
        },
        "optimization": {
            "algorithm": "NSGA-II",
            "seed": 42,
            "population_size": 4,
            "generations": 1,
            "unique_candidates_evaluated": 2,
            "decision_space_size": 16,
            "cost_objective_enabled": True,
            "pareto_front": candidates,
        },
    }


class TestEconomicSensitivity(unittest.TestCase):
    def test_reprices_fixed_candidate_set_and_writes_auditable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "nsga2_results.json"
            output = root / "economic-sensitivity.json"
            source.write_text(json.dumps(make_report()), encoding="utf-8")

            report = run_economic_sensitivity(source, output, relative_change=0.2)

            self.assertEqual(report["method"], "one-factor-at-a-time fixed-candidate economic sensitivity")
            self.assertEqual(report["baseline_candidate_count"], 2)
            self.assertEqual(report["source_type"], "synthetic")
            self.assertEqual(report["input_summary"]["row_count"], 8760)
            self.assertEqual(report["baseline_optimizer"]["seed"], 42)
            self.assertEqual(len(report["scenarios"]), 16)
            self.assertTrue(output.exists())
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["baseline_candidate_count"], 2)
            self.assertIn("optimizer is not rerun", " ".join(saved["interpretation_limits"]))

            electricity_low = next(
                item for item in report["scenarios"]
                if item["parameter"] == "electricity_price_per_kwh" and item["direction"] == "low"
            )
            electricity_high = next(
                item for item in report["scenarios"]
                if item["parameter"] == "electricity_price_per_kwh" and item["direction"] == "high"
            )
            self.assertLess(
                electricity_low["annual_cost"]["median"],
                electricity_high["annual_cost"]["median"],
            )

    def test_public_cli_writes_parseable_provenance_report(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "nsga2_results.json"
            output = root / "economic-sensitivity.json"
            source.write_text(json.dumps(make_report()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "experiments/economic_sensitivity.py",
                    str(source),
                    "--relative-change", "0.2",
                    "--output", str(output),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )

            summary = json.loads(completed.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["scenario_count"], 16)
            self.assertEqual(report["source_type"], "synthetic")
            self.assertEqual(report["baseline_optimizer"]["seed"], 42)
            self.assertEqual(len(report["scenarios"]), 16)
            self.assertIn("not a bankable financial model", " ".join(report["interpretation_limits"]))

    def test_zero_baseline_economic_field_is_reported_as_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nsga2_results.json"
            source.write_text(json.dumps(make_report(electricity_price=0.0)), encoding="utf-8")

            report = run_economic_sensitivity(source, Path(directory) / "out.json")
            self.assertTrue(any(
                item["parameter"] == "electricity_price_per_kwh"
                for item in report["skipped_scenarios"]
            ))
            self.assertEqual(len(report["scenarios"]), 14)

    def test_rejects_negative_cost_assumptions_even_if_totals_could_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nsga2_results.json"
            report = make_report()
            report["parameter_configuration"]["economics"]["ro_capex"] = -1.0
            source.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ro_capex must be a finite non-negative"):
                run_economic_sensitivity(source, Path(directory) / "out.json")

    def test_rejects_negative_candidate_usage_when_unit_price_is_zero(self):
        economics = make_report(electricity_price=0.0)["parameter_configuration"]["economics"]
        with self.assertRaisesRegex(ValueError, "energy and water quantities must be finite and non-negative"):
            _annual_cost(
                {
                    "annual_energy_used_by_flexible_loads_kwh": -1.0,
                    "annual_water_produced_m3": 0.0,
                },
                economics,
            )

    def test_rejects_non_hourly_or_invalid_quality_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nsga2_results.json"
            report = make_report()
            report["input_summary"]["interval_minutes"] = 15
            source.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complete-calendar-year hourly"):
                run_economic_sensitivity(source, Path(directory) / "out.json")

            report = make_report()
            report["data_quality_report"]["status"] = "invalid"
            source.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complete-calendar-year hourly"):
                run_economic_sensitivity(source, Path(directory) / "out.json")

    def test_rejects_partial_year_input_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nsga2_results.json"
            report = make_report()
            report["input_summary"]["row_count"] = 24
            source.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complete-calendar-year"):
                run_economic_sensitivity(source, Path(directory) / "out.json")

    def test_rejects_incomplete_or_invalid_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nsga2_results.json"
            report = make_report()
            report["parameter_configuration"]["economics_completeness"][
                "complete_for_current_declared_fields"
            ] = False
            source.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lifecycle-cost objective enabled"):
                run_economic_sensitivity(source, Path(directory) / "out.json")

            source.write_text(json.dumps(make_report()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "relative_change"):
                run_economic_sensitivity(source, Path(directory) / "out.json", relative_change=1.0)


if __name__ == "__main__":
    unittest.main()
