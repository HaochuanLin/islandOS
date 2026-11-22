"""Tests for strict Open Power System Data ingestion."""
import csv
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import islandos_core.opsd_adapter as opsd_adapter
from islandos_core.opsd_adapter import load_opsd_singleindex_csv


class TestOPSDAdapter(unittest.TestCase):
    def setUp(self):
        self.columns = [
            "utc_timestamp",
            "AT_load_actual_entsoe_transparency",
            "AT_solar_generation_actual",
            "AT_wind_onshore_generation_actual",
            "AT_price_day_ahead",
        ]

    def write_csv(self, rows, extra_columns=()):
        temp = tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                           suffix=".csv", delete=False)
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        writer = csv.DictWriter(temp, fieldnames=self.columns + list(extra_columns))
        writer.writeheader()
        writer.writerows(rows)
        temp.close()
        return temp.name

    def make_rows(self, count=80):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        return [
            {
                "utc_timestamp": (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H%M%SZ"),
                "AT_load_actual_entsoe_transparency": str(100.0 + i),
                "AT_solar_generation_actual": str(max(0.0, 20.0 - abs(i % 24 - 12))),
                "AT_wind_onshore_generation_actual": str(30.0 + i / 10),
                "AT_price_day_ahead": str(-5.0 if i % 24 < 3 else 40.0),
            }
            for i in range(count)
        ]

    def test_loads_four_signals_with_utc_units_and_provenance(self):
        path = self.write_csv(self.make_rows())
        result = load_opsd_singleindex_csv(path, "AT")
        self.assertEqual(len(result.timestamps), 80)
        self.assertEqual(result.timestamps[0], datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(set(result.history), {"load", "solar", "wind", "price"})
        self.assertEqual(result.units["load"], "MW")
        self.assertEqual(result.units["price"], "EUR/MWh")
        self.assertEqual(result.source_version, "2020-10-06")
        self.assertEqual(len(result.data_sha256), 64)
        self.assertLess(result.history["price"][0], 0.0)

    def test_records_exact_source_file_hash_and_normalized_history_hash(self):
        path = self.write_csv(self.make_rows(12))
        expected_file_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()

        result = load_opsd_singleindex_csv(path, "AT")

        self.assertEqual(result.source_file_sha256, expected_file_hash)
        self.assertEqual(result.selected_history_sha256, result.data_sha256)
        self.assertNotEqual(result.source_file_sha256, result.selected_history_sha256)

    def test_dataset_collections_are_immutable_snapshots(self):
        result = load_opsd_singleindex_csv(
            self.write_csv(self.make_rows(12)), "AT"
        )
        selected_digest = result.selected_history_sha256
        original_load = result.history["load"]

        with self.assertRaises(TypeError):
            result.history["load"] = (999.0,)
        with self.assertRaises(TypeError):
            result.units["load"] = "kW"
        with self.assertRaises(TypeError):
            result.source_columns["load"] = "tampered_column"

        self.assertEqual(result.history["load"], original_load)
        self.assertEqual(result.selected_history_sha256, selected_digest)

    def test_irrelevant_source_columns_change_only_the_raw_file_hash(self):
        rows = self.make_rows(12)
        original_path = self.write_csv(rows)
        extended_path = self.write_csv(rows, extra_columns=("UNUSED_METADATA",))

        original = load_opsd_singleindex_csv(original_path, "AT")
        extended = load_opsd_singleindex_csv(extended_path, "AT")

        self.assertNotEqual(original.source_file_sha256, extended.source_file_sha256)
        self.assertEqual(original.selected_history_sha256, extended.selected_history_sha256)

    def test_rejects_source_file_mutated_during_ingestion(self):
        path = self.write_csv(self.make_rows(12))
        original_parser = opsd_adapter._parse_utc_timestamp
        mutated = False

        def mutate_source_once(raw, line_number):
            nonlocal mutated
            if not mutated:
                # The CSV header has already been read when the first data
                # timestamp is parsed. Change the opened file in place so the
                # post-ingestion digest must detect the inconsistent snapshot.
                with open(path, "r+b") as handle:
                    handle.seek(0)
                    handle.write(b"#")
                mutated = True
            return original_parser(raw, line_number)

        with patch(
            "islandos_core.opsd_adapter._parse_utc_timestamp",
            side_effect=mutate_source_once,
        ):
            with self.assertRaisesRegex(ValueError, "changed while it was being read"):
                load_opsd_singleindex_csv(path, "AT")

    def test_supports_selected_signal_subset_and_utc_window(self):
        path = self.write_csv(self.make_rows())
        start = datetime(2020, 1, 1, 12, tzinfo=timezone.utc)
        end = datetime(2020, 1, 2, 12, tzinfo=timezone.utc)
        result = load_opsd_singleindex_csv(
            path, "AT", required_signals=("load", "wind"),
            start_utc=start, end_utc=end,
        )
        self.assertEqual(len(result.timestamps), 24)
        self.assertEqual(set(result.history), {"load", "wind"})
        self.assertEqual(result.timestamps[0], start)
        self.assertEqual(result.timestamps[-1], end - timedelta(hours=1))

    def test_prefers_total_wind_when_available(self):
        rows = self.make_rows(3)
        columns = self.columns + ["AT_wind_generation_actual"]
        temp = tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                           suffix=".csv", delete=False)
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        writer = csv.DictWriter(temp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            row["AT_wind_generation_actual"] = "55.0"
            writer.writerow(row)
        temp.close()
        result = load_opsd_singleindex_csv(
            temp.name, "AT", required_signals=("wind",)
        )
        self.assertEqual(result.history["wind"], (55.0, 55.0, 55.0))

    def test_rejects_missing_columns_and_missing_values(self):
        path = self.write_csv(self.make_rows())
        with self.assertRaisesRegex(ValueError, "missing required column"):
            load_opsd_singleindex_csv(path, "DE", required_signals=("load",))
        rows = self.make_rows()
        rows[4]["AT_solar_generation_actual"] = ""
        path = self.write_csv(rows)
        with self.assertRaisesRegex(ValueError, "missing solar value"):
            load_opsd_singleindex_csv(path, "AT")

    def test_rejects_gaps_nonfinite_values_and_invalid_bounds(self):
        rows = self.make_rows()
        rows[5]["utc_timestamp"] = (datetime(2020, 1, 1, tzinfo=timezone.utc)
                                     + timedelta(hours=6)).strftime("%Y-%m-%dT%H%M%SZ")
        path = self.write_csv(rows)
        with self.assertRaisesRegex(ValueError, "contiguous hourly"):
            load_opsd_singleindex_csv(path, "AT")

        rows = self.make_rows()
        rows[3]["AT_load_actual_entsoe_transparency"] = "nan"
        path = self.write_csv(rows)
        with self.assertRaisesRegex(ValueError, "non-finite load"):
            load_opsd_singleindex_csv(path, "AT")

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            load_opsd_singleindex_csv(
                self.write_csv(self.make_rows()), "AT",
                start_utc=datetime(2020, 1, 1),
            )

    def test_rejects_duplicate_csv_headers(self):
        temp = tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                           suffix=".csv", delete=False)
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        temp.write("utc_timestamp,AT_load_actual_entsoe_transparency,"
                   "AT_load_actual_entsoe_transparency\n")
        temp.write("2020-01-01T000000Z,10,11\n")
        temp.close()
        with self.assertRaisesRegex(ValueError, "duplicate column names"):
            load_opsd_singleindex_csv(
                temp.name, "AT", required_signals=("load",)
            )

    def test_rejects_negative_physical_values_but_keeps_negative_price(self):
        rows = self.make_rows()
        rows[0]["AT_wind_onshore_generation_actual"] = "-1"
        path = self.write_csv(rows)
        with self.assertRaisesRegex(ValueError, "negative wind"):
            load_opsd_singleindex_csv(path, "AT")


if __name__ == "__main__":
    unittest.main()
