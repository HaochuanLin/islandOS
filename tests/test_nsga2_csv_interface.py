"""End-to-end tests for the user CSV -> NSGA-II -> output interface."""
import csv
import tempfile
import unittest
from pathlib import Path

from experiments.run_nsga2_from_csv import run_from_csv


FIELDS = [
    "timestamp", "wind_kw", "pv_kw", "critical_load_kw",
    "water_demand_m3", "cooling_demand_kw_th",
]


class TestNSGA2CSVInterface(unittest.TestCase):
    def _write_csv(self, path, rows):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def _rows(self, count=8, critical_shortfall=False):
        rows = []
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(count):
            rows.append({
                "timestamp": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                "wind_kw": 350 if i % 2 == 0 else 0,
                "pv_kw": 200 if i in (2, 3, 5) else 0,
                "critical_load_kw": 600 if critical_shortfall and i == 1 else 100,
                "water_demand_m3": 20,
                "cooling_demand_kw_th": 50,
            })
        return rows

    def test_real_data_interface_writes_json_and_pareto_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "site.csv"
            output = root / "out"
            self._write_csv(source, self._rows())
            result = run_from_csv(
                source, output, source_type="measured",
                population_size=8, generations=2, seed=7,
            )
            self.assertEqual(result["input_summary"]["quality_status"], "valid")
            self.assertEqual(result["input_summary"]["row_count"], 8)
            self.assertEqual(result["input_summary"]["critical_shortfall_hours"], 0)
            self.assertTrue((output / "nsga2_results.json").exists())
            self.assertTrue((output / "pareto_front.csv").exists())
            with (output / "pareto_front.csv").open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                self.assertIn("water_unmet_m3", reader.fieldnames)
                self.assertGreaterEqual(len(list(reader)), 1)

    def test_critical_shortfall_fails_closed_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "site.csv"
            self._write_csv(source, self._rows(critical_shortfall=True))
            with self.assertRaisesRegex(ValueError, "Critical electricity demand is unmet"):
                run_from_csv(
                    source, root / "out", source_type="measured",
                    population_size=8, generations=1, seed=7,
                )

    def test_invalid_timestamp_or_gap_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "site.csv"
            rows = self._rows()
            rows[3]["timestamp"] = "2026-01-01T08:00:00Z"
            self._write_csv(source, rows)
            with self.assertRaisesRegex(ValueError, "failed quality validation"):
                run_from_csv(
                    source, root / "out", source_type="measured",
                    population_size=8, generations=1, seed=7,
                )


if __name__ == "__main__":
    unittest.main()
