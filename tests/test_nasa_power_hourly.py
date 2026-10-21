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


if __name__ == "__main__":
    unittest.main()
