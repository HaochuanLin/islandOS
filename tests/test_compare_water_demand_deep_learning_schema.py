"""Schema regression tests for the optional PyTorch water-demand experiment."""
import tempfile
import unittest
from pathlib import Path

try:
    from experiments.compare_water_demand_deep_learning import load_series
except SystemExit:  # PyTorch is an optional dependency outside its dedicated workflow.
    load_series = None


@unittest.skipIf(load_series is None, "optional PyTorch dependency is not installed")
class DeepLearningInputSchemaTests(unittest.TestCase):
    def test_rejects_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            source.write_text(
                "timestamp,water_demand_m3,water_demand_m3\\n"
                "2025-01-01T00:00:00Z,1,2\\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate columns"):
                load_series(source)

    def test_rejects_extra_row_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            source.write_text(
                "timestamp,water_demand_m3\\n"
                "2025-01-01T00:00:00Z,1,unexpected\\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "extra fields"):
                load_series(source)


if __name__ == "__main__":
    unittest.main()
