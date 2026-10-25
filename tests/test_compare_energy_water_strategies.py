"""Regression tests for the generic energy-to-water strategy comparison."""
import csv
import tempfile
import unittest
from pathlib import Path

from experiments.compare_energy_water_strategies import (
    Config,
    SiteStep,
    compare_strategies,
    load_site_steps,
)


def step(ts, surplus=0, diesel=0, price=0.2, off_peak=False,
         grid=True, water_demand=0, backup=0):
    return SiteStep(
        timestamp=ts,
        renewable_surplus_kw=surplus,
        diesel_displacement_potential_kw=diesel,
        grid_price_per_kwh=price,
        off_peak=off_peak,
        grid_available=grid,
        water_demand_m3=water_demand,
        backup_available_kw=backup,
    )


class EnergyWaterStrategyComparisonTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(
            ro_rated_power_kw=10,
            specific_energy_kwh_m3=5,
            tank_capacity_m3=20,
            initial_water_m3=0,
            min_run_hours=2,
            dt_hours=1,
            diesel_cost_per_kwh=0.6,
        )

    def test_surplus_strategy_uses_only_surplus_and_produces_expected_water(self):
        steps = [
            step("2026-01-01T00:00", surplus=10, diesel=3, water_demand=1),
            step("2026-01-01T01:00", surplus=10, diesel=2, water_demand=1),
        ]
        detail, summaries = compare_strategies(steps, self.config)
        surplus = next(row for row in summaries if row["strategy"] == "surplus_only")
        self.assertEqual(surplus["surplus_energy_to_ro_kwh"], 20)
        self.assertEqual(surplus["grid_energy_to_ro_kwh"], 0)
        self.assertEqual(surplus["backup_energy_to_ro_kwh"], 0)
        self.assertEqual(surplus["water_produced_m3"], 4)
        self.assertEqual(surplus["direct_diesel_displacement_potential_kwh"], 5)
        rows = [r for r in detail if r["strategy"] == "surplus_only"]
        self.assertEqual([r["ro_source"] for r in rows], ["surplus", "surplus"])

    def test_off_peak_strategy_requires_grid_and_off_peak(self):
        steps = [
            step("2026-01-01T00:00", surplus=10, price=0.1, off_peak=True, grid=True),
            step("2026-01-01T01:00", price=0.1, off_peak=True, grid=True),
            step("2026-01-01T02:00", price=0.4, off_peak=False, grid=True),
        ]
        detail, summaries = compare_strategies(steps, self.config)
        off_peak = next(row for row in summaries if row["strategy"] == "off_peak_only")
        self.assertEqual(off_peak["grid_energy_to_ro_kwh"], 20)
        self.assertAlmostEqual(off_peak["grid_energy_cost"], 2.0)
        self.assertEqual(off_peak["renewable_surplus_available_kwh"], 10)
        self.assertEqual(off_peak["renewable_surplus_unused_kwh"], 10)
        rows = [r for r in detail if r["strategy"] == "off_peak_only"]
        self.assertEqual([r["ro_source"] for r in rows], ["grid", "grid", "off"])

    def test_hybrid_prefers_surplus_then_uses_off_peak_grid(self):
        steps = [
            step("2026-01-01T00:00", surplus=10, off_peak=False, grid=True),
            step("2026-01-01T01:00", surplus=0, off_peak=True, grid=True, price=0.1),
        ]
        detail, summaries = compare_strategies(steps, self.config)
        hybrid = next(row for row in summaries if row["strategy"] == "hybrid_surplus_then_off_peak")
        self.assertEqual(hybrid["surplus_energy_to_ro_kwh"], 10)
        self.assertEqual(hybrid["grid_energy_to_ro_kwh"], 10)
        rows = [r for r in detail if r["strategy"] == "hybrid_surplus_then_off_peak"]
        self.assertEqual([r["ro_source"] for r in rows], ["surplus", "grid"])

    def test_minimum_run_window_blocks_short_surplus_event(self):
        steps = [
            step("2026-01-01T00:00", surplus=10),
            step("2026-01-01T01:00", surplus=0),
        ]
        _, summaries = compare_strategies(steps, self.config)
        surplus = next(row for row in summaries if row["strategy"] == "surplus_only")
        self.assertEqual(surplus["ro_run_hours"], 0)
        self.assertEqual(surplus["water_produced_m3"], 0)

    def test_emergency_backup_energy_cost_is_separate(self):
        steps = [
            step("2026-01-01T00:00", backup=10),
            step("2026-01-01T01:00", backup=10),
        ]
        _, summaries = compare_strategies(steps, self.config)
        backup = next(row for row in summaries if row["strategy"] == "emergency_backup")
        self.assertEqual(backup["backup_energy_to_ro_kwh"], 20)
        self.assertAlmostEqual(backup["backup_energy_cost_estimate"], 12.0)
        self.assertEqual(backup["grid_energy_to_ro_kwh"], 0)

    def test_baseline_does_not_run_ro_but_still_reports_water_shortfall(self):
        steps = [step("2026-01-01T00:00", water_demand=2)]
        _, summaries = compare_strategies(steps, self.config)
        baseline = next(row for row in summaries if row["strategy"] == "no_ro_baseline")
        self.assertEqual(baseline["water_produced_m3"], 0)
        self.assertEqual(baseline["unmet_water_demand_m3"], 2)


    def test_minimum_run_hours_respects_half_hour_time_steps(self):
        config = Config(
            ro_rated_power_kw=10,
            specific_energy_kwh_m3=5,
            tank_capacity_m3=20,
            initial_water_m3=0,
            min_run_hours=2,
            dt_hours=0.5,
        )
        steps = [
            step("2026-01-01T00:00", surplus=10),
            step("2026-01-01T00:30", surplus=10),
            step("2026-01-01T01:00", surplus=10),
            step("2026-01-01T01:30", surplus=10),
        ]
        _, summaries = compare_strategies(steps, config)
        surplus = next(row for row in summaries if row["strategy"] == "surplus_only")
        self.assertEqual(surplus["ro_run_hours"], 2)
        self.assertEqual(surplus["surplus_energy_to_ro_kwh"], 20)

    def test_direct_api_rejects_empty_timestep_series(self):
        with self.assertRaisesRegex(ValueError, "at least one timestep"):
            compare_strategies([], self.config)

    def test_direct_api_rejects_non_finite_and_negative_step_values(self):
        invalid_steps = [
            step("2026-01-01T00:00", surplus=float("nan")),
            step("2026-01-01T00:00", water_demand=-1),
            step("2026-01-01T00:00", backup=float("inf")),
            step("2026-01-01T00:00", price=True),
        ]
        for invalid in invalid_steps:
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "Step 1:"):
                    compare_strategies([invalid], self.config)

    def test_direct_api_rejects_non_boolean_dispatch_flags(self):
        invalid = SiteStep(
            timestamp="2026-01-01T00:00",
            renewable_surplus_kw=0,
            diesel_displacement_potential_kw=0,
            grid_price_per_kwh=0.2,
            off_peak=1,
            grid_available=True,
            water_demand_m3=0,
        )
        with self.assertRaisesRegex(ValueError, "off_peak must be a boolean"):
            compare_strategies([invalid], self.config)

    def test_csv_loader_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("timestamp,renewable_surplus_kw\n2026-01-01T00:00,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required columns"):
                load_site_steps(path)

    def test_csv_loader_rejects_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.csv"
            path.write_text(
                "timestamp,renewable_surplus_kw,renewable_surplus_kw,"
                "diesel_displacement_potential_kw,grid_price_per_kwh,off_peak,"
                "grid_available,water_demand_m3\n"
                "2026-01-01T00:00,1,2,0,0.1,true,true,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate column names"):
                load_site_steps(path)

    def test_csv_loader_rejects_extra_row_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "extra.csv"
            path.write_text(
                "timestamp,renewable_surplus_kw,diesel_displacement_potential_kw,"
                "grid_price_per_kwh,off_peak,grid_available,water_demand_m3\n"
                "2026-01-01T00:00,1,0,0.1,true,true,1,unexpected\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "extra fields"):
                load_site_steps(path)

    def test_csv_loader_rejects_short_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.csv"
            path.write_text(
                "timestamp,renewable_surplus_kw,diesel_displacement_potential_kw,"
                "grid_price_per_kwh,off_peak,grid_available,water_demand_m3\n"
                "2026-01-01T00:00,1,0,0.1,true\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing field"):
                load_site_steps(path)

    def test_csv_loader_rejects_duplicate_instants_with_different_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "same-instant.csv"
            path.write_text(
                "timestamp,renewable_surplus_kw,diesel_displacement_potential_kw,"
                "grid_price_per_kwh,off_peak,grid_available,water_demand_m3\n"
                "2026-01-01T00:00:00+00:00,1,0,0.1,true,true,1\n"
                "2026-01-01T01:00:00+01:00,1,0,0.1,true,true,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "strictly increasing in time"):
                load_site_steps(path)

    def test_csv_loader_rejects_mixed_timezone_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed-timezone.csv"
            path.write_text(
                "timestamp,renewable_surplus_kw,diesel_displacement_potential_kw,"
                "grid_price_per_kwh,off_peak,grid_available,water_demand_m3\n"
                "2026-01-01T00:00:00+00:00,1,0,0.1,true,true,1\n"
                "2026-01-01T01:00:00,1,0,0.1,true,true,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "mix timezone-aware"):
                load_site_steps(path)

    def test_csv_loader_rejects_negative_physical_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "timestamp", "renewable_surplus_kw", "diesel_displacement_potential_kw",
                    "grid_price_per_kwh", "off_peak", "grid_available", "water_demand_m3",
                ])
                writer.writerow(["2026-01-01T00:00", "-1", "0", "0.1", "1", "1", "0"])
            with self.assertRaisesRegex(ValueError, "renewable_surplus_kw"):
                load_site_steps(path)


    def test_dispatch_rejects_irregular_timestamp_intervals(self):
        steps = [
            step("2026-01-01T00:00", surplus=10),
            step("2026-01-01T01:00", surplus=10),
            step("2026-01-01T03:00", surplus=10),
        ]
        with self.assertRaisesRegex(ValueError, "timestamp interval is 7200 seconds"):
            compare_strategies(steps, self.config)

    def test_dispatch_requires_interval_to_match_dt_hours(self):
        config = Config(
            ro_rated_power_kw=10,
            specific_energy_kwh_m3=5,
            tank_capacity_m3=20,
            initial_water_m3=0,
            min_run_hours=1,
            dt_hours=0.5,
        )
        steps = [
            step("2026-01-01T00:00", surplus=10),
            step("2026-01-01T01:00", surplus=10),
        ]
        with self.assertRaisesRegex(ValueError, "dt_hours=0.5 requires 1800 seconds"):
            compare_strategies(steps, config)

    def test_dispatch_accepts_consistent_timezone_aware_intervals(self):
        steps = [
            step("2026-01-01T00:00:00+00:00", surplus=10),
            step("2026-01-01T01:00:00+00:00", surplus=10),
        ]
        _, summaries = compare_strategies(steps, self.config)
        self.assertEqual(len(summaries), 5)


if __name__ == "__main__":
    unittest.main()
