"""Unit tests for NASA POWER ingestion; all responses are mocked."""
import unittest
from urllib.parse import parse_qs, urlparse

from data_sources.nasa_power_hourly import (
    PARAMETERS,
    build_request_url,
    parse_response,
)


def sample_payload():
    return {
        "header": {"api": "hourly"},
        "parameters": {
            "ALLSKY_SFC_SW_DWN": {"units": "source-defined"},
            "T2M": {"units": "source-defined"},
            "WS10M": {"units": "source-defined"},
        },
        "geometry": {"coordinates": [-63.5, -35.2, 100]},
        "properties": {"parameter": {
            "ALLSKY_SFC_SW_DWN": {"2020010100": 0.0, "2020010101": 0.3},
            "T2M": {"2020010100": 18.0, "2020010101": 18.5},
            "WS10M": {"2020010100": 4.0, "2020010101": 4.2},
        }},
    }


class TestNasaPowerImporter(unittest.TestCase):
    def test_url_uses_utc_and_expected_parameters(self):
        url = build_request_url(-35.2, -63.5, "20200101", "20200102")
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["time-standard"], ["UTC"])
        self.assertEqual(query["parameters"], [",".join(PARAMETERS)])
        self.assertEqual(query["format"], ["JSON"])

    def test_rejects_invalid_coordinates_dates_and_ranges(self):
        for args in [
            (91, 0, "20200101", "20200102"),
            (0, 181, "20200101", "20200102"),
            (float("nan"), 0, "20200101", "20200102"),
            (0, 0, "20201301", "20200102"),
            (0, 0, "20200103", "20200102"),
        ]:
            with self.assertRaises(ValueError):
                build_request_url(*args)

    def test_parses_aligned_records_and_utc_timestamps(self):
        rows, metadata = parse_response(sample_payload())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["timestamp_utc"], "2020-01-01T00:00:00Z")
        self.assertEqual(rows[1]["T2M"], 18.5)
        self.assertIn("geometry", metadata)

    def test_rejects_missing_or_misaligned_parameters(self):
        payload = sample_payload()
        del payload["properties"]["parameter"]["WS10M"]
        with self.assertRaisesRegex(ValueError, "missing parameters"):
            parse_response(payload)
        payload = sample_payload()
        payload["properties"]["parameter"]["WS10M"] = {"2020010100": 4.0}
        with self.assertRaisesRegex(ValueError, "do not align"):
            parse_response(payload)

    def test_rejects_malformed_payload_and_non_numeric_values(self):
        with self.assertRaisesRegex(ValueError, "missing properties.parameter"):
            parse_response({})
        payload = sample_payload()
        payload["properties"]["parameter"]["T2M"]["2020010100"] = "unknown"
        with self.assertRaisesRegex(ValueError, "Non-numeric"):
            parse_response(payload)
        payload = sample_payload()
        payload["properties"]["parameter"]["T2M"]["2020010100"] = float("inf")
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            parse_response(payload)

    def test_fill_values_are_blank_and_counted_not_zeroed(self):
        payload = sample_payload()
        payload["properties"]["parameter"]["WS10M"]["2020010101"] = -999.0
        rows, metadata = parse_response(payload)
        self.assertEqual(rows[1]["WS10M"], "")
        self.assertEqual(metadata["fill_value_counts"]["WS10M"], 1)
        self.assertIn("never replaced with zero", metadata["fill_value_policy"])

    def test_rejects_hourly_gaps_and_invalid_timestamp_keys(self):
        payload = sample_payload()
        for name in PARAMETERS:
            payload["properties"]["parameter"][name] = {
                "2020010100": payload["properties"]["parameter"][name]["2020010100"],
                "2020010102": payload["properties"]["parameter"][name]["2020010101"],
            }
        with self.assertRaisesRegex(ValueError, "gap or duplicate"):
            parse_response(payload)
        payload = sample_payload()
        for name in PARAMETERS:
            values = payload["properties"]["parameter"][name]
            values["2020023000"] = values.pop("2020010101")
        with self.assertRaisesRegex(ValueError, "Unexpected NASA POWER timestamp"):
            parse_response(payload)


if __name__ == "__main__":
    unittest.main()
