"""Tests for the open Mafate microgrid time-series importer."""
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from experiments.import_mafate_microgrid_data import import_dataset


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def make_dataset(root: Path) -> None:
    write_csv(root / "Meteo_dataset.csv",
              ["Date", "Gincl", "Ghi", "Tpv", "Ta", "Rh", "Wd", "Ws", "Press"],
              [
                  {"Date": "01/05/2020 00:00:00", "Gincl": 0.2, "Ghi": 0.1, "Tpv": 25, "Ta": 20, "Rh": 70, "Wd": 90, "Ws": 2, "Press": 1000},
                  {"Date": "01/05/2020 00:00:20", "Gincl": 0.4, "Ghi": 0.3, "Tpv": 27, "Ta": 22, "Rh": 68, "Wd": 100, "Ws": 4, "Press": 1002},
                  {"Date": "01/05/2020 01:00:00", "Gincl": 0.0, "Ghi": 0.0, "Tpv": 24, "Ta": 19, "Rh": 72, "Wd": 80, "Ws": 1, "Press": 1001},
              ])
    write_csv(root / "Solar_plant_dataset.csv",
              ["Date", "Pout", "Ppv1", "Ppv2", "Upv1", "Upv2", "Ubat", "Ibat", "Tbat"],
              [
                  {"Date": "01/05/2020 00:00:00", "Pout": 1, "Ppv1": 0.5, "Ppv2": 0.5, "Upv1": 100, "Upv2": 101, "Ubat": 48, "Ibat": 2, "Tbat": 25},
                  {"Date": "01/05/2020 00:01:00", "Pout": 3, "Ppv1": 1.5, "Ppv2": 1.5, "Upv1": 102, "Upv2": 103, "Ubat": 49, "Ibat": 4, "Tbat": 26},
                  {"Date": "01/05/2020 01:00:00", "Pout": 0, "Ppv1": 0, "Ppv2": 0, "Upv1": 0, "Upv2": 0, "Ubat": 48, "Ibat": -1, "Tbat": 24},
              ])
    write_csv(root / "Demand_house_1_dataset.csv",
              ["Date", "Input1", "Input2", "Input3", "Input4"],
              [
                  {"Date": "01/05/2020 00:00:00", "Input1": 100, "Input2": 200, "Input3": 300, "Input4": 600},
                  {"Date": "01/05/2020 00:01:00", "Input1": 200, "Input2": 300, "Input3": 400, "Input4": 900},
                  {"Date": "01/05/2020 01:00:00", "Input1": 100, "Input2": 100, "Input3": 100, "Input4": 300},
              ])
    write_csv(root / "Demand_house_2_dataset.csv",
              ["Date", "Input1", "Input2", "Input3", "Input4", "Input5"],
              [
                  {"Date": "01/05/2020 00:00:00", "Input1": 100, "Input2": 200, "Input3": 300, "Input4": 400, "Input5": 1000},
                  {"Date": "01/05/2020 00:01:00", "Input1": 100, "Input2": 200, "Input3": 300, "Input4": 400, "Input5": 1200},
              ])
    write_csv(root / "Demand_house_3_dataset.csv",
              ["Date", "Input1", "Input2", "Input3", "Input4"],
              [
                  {"Date": "01/05/2020 00:00:00", "Input1": 800, "Input2": 200, "Input3": 300, "Input4": 400},
                  {"Date": "01/05/2020 00:01:00", "Input1": 1000, "Input2": 200, "Input3": 300, "Input4": 400},
                  {"Date": "01/05/2020 01:00:00", "Input1": 500, "Input2": 100, "Input3": 200, "Input4": 300},
              ])


class MafateImporterTests(unittest.TestCase):
    def test_resamples_measurements_without_filling_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw"
            output = root / "out"
            source.mkdir()
            make_dataset(source)

            manifest = import_dataset(source, output)

            self.assertEqual(manifest["row_counts"]["microgrid_hourly.csv"], 2)
            self.assertEqual(manifest["source_row_counts"]["meteo"], 3)
            self.assertEqual(
                set(manifest["source_file_sha256"]),
                {"meteo", "solar", "house_1", "house_2", "house_3"},
            )
            expected_hash = hashlib.sha256(
                (source / "Meteo_dataset.csv").read_bytes()
            ).hexdigest()
            self.assertEqual(manifest["source_file_sha256"]["meteo"], expected_hash)
            with (output / "microgrid_hourly.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["timestamp_local"], "2020-05-01T00:00:00")
            self.assertAlmostEqual(float(rows[0]["ghi_horizontal_kw_m2"]), 0.2)
            self.assertEqual(rows[0]["meteo_samples"], "2")
            self.assertAlmostEqual(float(rows[0]["inverter_output_power_kw"]), 2.0)
            self.assertAlmostEqual(float(rows[0]["house_1_load_kw"]), 0.75)
            self.assertAlmostEqual(float(rows[0]["house_2_load_kw"]), 1.1)
            self.assertAlmostEqual(float(rows[0]["house_3_load_kw"]), 0.9)
            self.assertEqual(rows[1]["house_2_samples"], "0")
            self.assertEqual(rows[1]["house_2_load_kw"], "")
            self.assertEqual(manifest["license"], "Creative Commons Attribution 4.0 International (CC BY 4.0); attribute the authors and dataset.")
            self.assertTrue((output / "meteo_hourly.csv").is_file())
            self.assertTrue((output / "solar_plant_hourly.csv").is_file())
            self.assertTrue((output / "house_loads_hourly.csv").is_file())
            self.assertTrue((output / "manifest.json").is_file())

    def test_rejects_missing_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(FileNotFoundError, "Meteo_dataset.csv"):
                import_dataset(root, root / "out")

    def test_rejects_headers_that_collide_after_whitespace_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw"
            output = root / "out"
            source.mkdir()
            make_dataset(source)
            path = source / "Meteo_dataset.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0] = lines[0].replace("Date,Gincl,Ghi", "Date,Gincl, Gincl")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate columns after whitespace normalization"):
                import_dataset(source, output)

    def test_rejects_extra_source_csv_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw"
            output = root / "out"
            source.mkdir()
            make_dataset(source)
            path = source / "Meteo_dataset.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[1] += ",unexpected"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra fields"):
                import_dataset(source, output)


if __name__ == "__main__":
    unittest.main()
