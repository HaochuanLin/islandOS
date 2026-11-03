import io
import unittest

from ro_costing import ROCostRates
from ro_historical_baseline import reconstruct_historical_ro_cost


CSV = """timestamp,energy_kwh,water_produced_m3,electricity_price_per_kwh,runtime_hours,start_events
2026-01-01T00:00:00+00:00,10,2,0.5,1,1
2026-01-01T01:00:00+00:00,8,2,0.25,1,0
"""


class TestHistoricalBaseline(unittest.TestCase):
    def setUp(self):
        self.rates = ROCostRates(
            currency="CNY",
            electricity_price_per_kwh=0.0,
            chemical_cost_per_m3=0.1,
            variable_om_cost_per_m3=0.05,
            maintenance_cost_per_runtime_hour=1.0,
            start_stop_cost_per_event=2.0,
        )

    def test_reconstructs_uploaded_period_without_annualizing(self):
        result = reconstruct_historical_ro_cost(
            io.StringIO(CSV), self.rates, dt_hours=1.0,
            expected_interval_hours=1.0,
        )
        report = result["cost_report"]
        self.assertEqual(result["status"], "historical_cost_reconstructed")
        self.assertTrue(result["is_customer_supplied_data"])
        self.assertEqual(result["measurement_status"], "not independently verified")
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["represented_hours"], 2.0)
        self.assertEqual(result["timestamp_span_hours"], 1.0)
        self.assertAlmostEqual(report.electricity_cost, 7.0)
        self.assertAlmostEqual(report.total_operating_cost, 11.6)
        self.assertIsNone(result.get("annualized_cost"))

    def test_rejects_missing_columns(self):
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            reconstruct_historical_ro_cost(
                io.StringIO("timestamp,energy_kwh\n2026-01-01T00:00:00,1\n"),
                self.rates, dt_hours=1.0,
            )

    def test_rejects_timestamp_gaps_instead_of_filling_them(self):
        broken = CSV.replace("2026-01-01T01:00:00", "2026-01-01T03:00:00")
        with self.assertRaisesRegex(ValueError, "gap/irregular interval"):
            reconstruct_historical_ro_cost(
                io.StringIO(broken), self.rates, dt_hours=1.0,
                expected_interval_hours=1.0,
            )

    def test_rejects_non_monotonic_timestamps(self):
        broken = CSV.replace(
            "2026-01-01T01:00:00+00:00", "2025-12-31T23:00:00+00:00"
        )
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            reconstruct_historical_ro_cost(
                io.StringIO(broken), self.rates, dt_hours=1.0,
            )

    def test_rejects_missing_values_and_non_integer_start_events(self):
        broken = CSV.replace(",8,2,0.25,1,0", ",8,,0.25,1,0")
        with self.assertRaisesRegex(ValueError, "water_produced_m3"):
            reconstruct_historical_ro_cost(
                io.StringIO(broken), self.rates, dt_hours=1.0,
            )
        broken = CSV.replace(",8,2,0.25,1,0", ",8,2,0.25,1,0.5")
        with self.assertRaisesRegex(ValueError, "start_events must be an integer"):
            reconstruct_historical_ro_cost(
                io.StringIO(broken), self.rates, dt_hours=1.0,
            )


    def test_rejects_mixed_timezone_awareness(self):
        mixed = CSV.replace(
            "2026-01-01T01:00:00+00:00", "2026-01-01T01:00:00"
        )
        with self.assertRaisesRegex(ValueError, "consistent timezone"):
            reconstruct_historical_ro_cost(
                io.StringIO(mixed), self.rates, dt_hours=1.0,
            )

    def test_rejects_invalid_time_step_inputs(self):
        for value in (0, -1, float("nan"), True, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "dt_hours"):
                    reconstruct_historical_ro_cost(
                        io.StringIO(CSV), self.rates, dt_hours=value,
                    )
        for value in (0, -1, float("inf"), True, "1"):
            with self.subTest(expected_interval_hours=value):
                with self.assertRaisesRegex(ValueError, "expected_interval_hours"):
                    reconstruct_historical_ro_cost(
                        io.StringIO(CSV), self.rates, dt_hours=1.0,
                        expected_interval_hours=value,
                    )


if __name__ == "__main__":
    unittest.main()
