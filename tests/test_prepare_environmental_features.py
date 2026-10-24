"""Tests for auditable environmental feature preparation; no network required."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data_sources.prepare_environmental_features import (
    PARAMETERS,
    prepare_features,
)


class TestEnvironmentalFeatures(unittest.TestCase):
    def _fixture(self, directory, count=30):
        source = Path(directory) / "raw.csv"
        metadata = {
            "response_metadata": {
                "parameters": {name: {"units": "test-unit"} for name in PARAMETERS}
            }
        }
        source.with_suffix(".csv.metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", *PARAMETERS])
            writer.writeheader()
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            for i in range(count):
                row = {"timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z")}
                row.update({name: i + j for j, name in enumerate(PARAMETERS)})
                writer.writerow(row)
        return source

    def test_creates_lags_and_omits_24_hour_warmup(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._fixture(directory, 30)
            output = Path(directory) / "features.csv"
            result = prepare_features(source, output)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 6)
            self.assertEqual(result["warmup_rows_omitted"], 24)
            self.assertEqual(rows[0]["timestamp_utc"], "2024-01-02T00:00:00Z")
            self.assertEqual(float(rows[0]["allsky_sfc_sw_dwn_lag_24h"]), 0.0)
            self.assertEqual(float(rows[0]["allsky_sfc_sw_dwn_lag_1h"]), 23.0)
            self.assertEqual(result["units"]["T2M"], "test-unit")
            self.assertTrue(Path(str(output) + ".metadata.json").exists())

    def test_rejects_missing_provenance_units(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._fixture(directory)
            sidecar = source.with_suffix(".csv.metadata.json")
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            del data["response_metadata"]["parameters"]["T2M"]["units"]
            sidecar.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing source units"):
                prepare_features(source, Path(directory) / "out.csv")

    def test_rejects_gaps_and_missing_values_without_imputation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._fixture(directory, 30)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[5]["timestamp_utc"] = "2024-01-01T06:00:00Z"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", *PARAMETERS])
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "ordered hourly"):
                prepare_features(source, Path(directory) / "out.csv")

            source = self._fixture(directory, 30)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[26]["WS10M"] = ""
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", *PARAMETERS])
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "Missing WS10M"):
                prepare_features(source, Path(directory) / "out.csv")

    def test_rejects_short_series_and_non_finite_values(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._fixture(directory, 24)
            with self.assertRaisesRegex(ValueError, "Need at least"):
                prepare_features(source, Path(directory) / "out.csv")
            source = self._fixture(directory, 30)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[26]["T2M"] = "nan"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", *PARAMETERS])
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "Non-finite"):
                prepare_features(source, Path(directory) / "out.csv")

    def test_rejects_duplicate_and_extra_source_csv_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._fixture(directory, 30)
            output = Path(directory) / "features.csv"
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[0] = lines[0].replace("T2M", "ALLSKY_SFC_SW_DWN")
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate columns"):
                prepare_features(source, output)

            source = self._fixture(directory, 30)
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[1] += ",unexpected"
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra fields"):
                prepare_features(source, output)


if __name__ == "__main__":
    unittest.main()
