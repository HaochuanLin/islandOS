"""Tests for the explicitly synthetic loopback telemetry demo sender."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from islandos_telemetry_demo import generate_demo_samples, send_samples, wait_for_gateway


class FakeResponse:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"status":"accepted"}'


class TestSyntheticTelemetryDemo(unittest.TestCase):
    def test_generates_hourly_aligned_nonnegative_demo_samples(self):
        now = datetime(2026, 10, 23, 7, 35, tzinfo=timezone.utc)
        rows = generate_demo_samples(24, now=now)
        self.assertEqual(len(rows), 24)
        timestamps = [datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")) for row in rows]
        self.assertEqual(timestamps[-1].minute, 0)
        self.assertTrue(all((right - left).total_seconds() == 3600 for left, right in zip(timestamps, timestamps[1:])))
        self.assertTrue(all(row["quality_flag"] == "good" for row in rows))
        self.assertTrue(all(row["renewable_surplus_kw"] >= 0 for row in rows))
        self.assertTrue(all(row["water_demand_m3"] > 0 for row in rows))
        self.assertTrue(all(row["cooling_demand_kw_th"] > 0 for row in rows))
        self.assertTrue(all(row["device_id"] == "synthetic-demo-generator" for row in rows))

    def test_rejects_invalid_hour_counts(self):
        for hours in (True, 1, 169, 2.5, "24"):
            with self.subTest(hours=hours):
                with self.assertRaises(ValueError):
                    generate_demo_samples(hours)

    def test_posts_each_sample_to_loopback_gateway(self):
        rows = generate_demo_samples(3, now=datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc))
        with patch("islandos_telemetry_demo.urlopen", return_value=FakeResponse()) as open_url:
            self.assertEqual(send_samples("http://127.0.0.1:8765", rows), 3)
        self.assertEqual(open_url.call_count, 3)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8765/telemetry")
        self.assertEqual(request.get_method(), "POST")

    def test_waits_for_gateway_health_before_demo(self):
        class HealthResponse(FakeResponse):
            status = 200
            def read(self):
                return b'{"status":"ok"}'
        with patch("islandos_telemetry_demo.urlopen", return_value=HealthResponse()) as open_url:
            self.assertTrue(wait_for_gateway("http://127.0.0.1:8765", timeout=0.1))
        self.assertEqual(open_url.call_count, 1)
        self.assertEqual(open_url.call_args.args[0], "http://127.0.0.1:8765/health")

    def test_rejects_non_loopback_destination_in_cli(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "islandos_telemetry_demo.py", "--url", "http://example.com"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("loopback", result.stderr)


if __name__ == "__main__":
    unittest.main()
