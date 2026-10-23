"""Integration tests for the loopback-only read-only HTTP telemetry gateway."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "islandos_gateway_server.py"


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestReadOnlyHTTPGateway(unittest.TestCase):
    def test_live_ingest_validates_persists_and_exposes_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = free_port()
            audit = Path(tmp) / "audit.jsonl"
            process = subprocess.Popen(
                [sys.executable, str(SERVER), "--host", "127.0.0.1",
                 "--port", str(port), "--max-age-seconds", "7200", "--audit-file", str(audit)],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            base = "http://127.0.0.1:%d" % port
            try:
                for _ in range(60):
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail("gateway exited early: %s %s" % (stdout, stderr))
                    try:
                        with urlopen(base + "/health", timeout=0.25) as response:
                            health = json.loads(response.read().decode("utf-8"))
                        break
                    except (URLError, TimeoutError):
                        time.sleep(0.1)
                else:
                    self.fail("gateway health endpoint did not become ready")
                self.assertEqual(health["status"], "ok")
                self.assertFalse(health["physical_write_performed"])

                now = datetime.now(timezone.utc)
                payload = {
                    "timestamp_utc": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    "renewable_surplus_kw": 18.5,
                    "water_demand_m3": 3.2,
                    "cooling_demand_kw_th": 6.5,
                    "quality_flag": "good",
                }
                request = Request(
                    base + "/telemetry",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    accepted = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 202)
                self.assertEqual(accepted["status"], "accepted")
                self.assertFalse(accepted["physical_write_performed"])

                with urlopen(base + "/latest", timeout=2) as response:
                    latest = json.loads(response.read().decode("utf-8"))
                self.assertTrue(latest["valid"])
                self.assertEqual(latest["values"]["renewable_surplus_kw"], 18.5)
                self.assertFalse(latest["physical_write_performed"])

                second_payload = dict(payload)
                second_payload["timestamp_utc"] = now.isoformat().replace("+00:00", "Z")
                second_payload["renewable_surplus_kw"] = 21.0
                second_payload["water_demand_m3"] = 3.6
                request = Request(
                    base + "/telemetry",
                    data=json.dumps(second_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 202)
                with urlopen(base + "/advice", timeout=5) as response:
                    advice = json.loads(response.read().decode("utf-8"))
                self.assertIn(advice["status"], {"advice_ready", "operator_review_required"})
                self.assertEqual(len(advice["policy_comparison"]), 4)
                self.assertEqual(len(advice["weight_sensitivity"]), 4)
                self.assertTrue(advice["operator_action_required"])
                self.assertFalse(advice["physical_write_performed"])

                records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(records), 2)
                self.assertTrue(all(record["valid"] for record in records))

                payload["timestamp_utc"] = now.isoformat().replace("+00:00", "Z")
                payload["renewable_surplus_kw"] = -1
                request = Request(
                    base + "/telemetry",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as rejected:
                    urlopen(request, timeout=2)
                self.assertEqual(rejected.exception.code, 422)
                rejected_body = json.loads(rejected.exception.read().decode("utf-8"))
                self.assertFalse(rejected_body["valid"])
                self.assertEqual(len(audit.read_text(encoding="utf-8").splitlines()), 2)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def test_non_loopback_bind_is_rejected(self):
        result = subprocess.run(
            [sys.executable, str(SERVER), "--host", "0.0.0.0", "--port", "8765"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("bind only to loopback", result.stderr)

    def test_wrong_content_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = free_port()
            process = subprocess.Popen(
                [sys.executable, str(SERVER), "--port", str(port),
                 "--audit-file", str(Path(tmp) / "audit.jsonl")],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            base = "http://127.0.0.1:%d" % port
            try:
                for _ in range(60):
                    try:
                        urlopen(base + "/health", timeout=0.25).close()
                        break
                    except (URLError, TimeoutError):
                        time.sleep(0.1)
                request = Request(
                    base + "/telemetry", data=b"{}", headers={"Content-Type": "text/plain"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as rejected:
                    urlopen(request, timeout=2)
                self.assertEqual(rejected.exception.code, 415)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
