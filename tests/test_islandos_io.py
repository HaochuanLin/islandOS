"""Tests for fail-closed telemetry and hardware-control safety boundary."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_io import (
    ControlRequest,
    SafetyContext,
    authorize_control,
    build_recommendation,
    validate_telemetry,
)


NOW = datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc)


def good_payload():
    return {
        "timestamp_utc": NOW.isoformat().replace("+00:00", "Z"),
        "device_id": "simulated-gateway-01",
        "quality_flag": "good",
        "renewable_surplus_kw": 42.0,
        "water_demand_m3": 5.0,
        "cooling_demand_kw_th": 8.0,
    }


class TestTelemetryValidation(unittest.TestCase):
    def test_accepts_fresh_timezone_aware_complete_message(self):
        frame = validate_telemetry(good_payload(), "test-gateway", received_at=NOW)
        self.assertTrue(frame.valid)
        self.assertEqual(frame.values["renewable_surplus_kw"], 42.0)
        self.assertEqual(frame.timestamp_utc, NOW)

    def test_rejects_stale_message(self):
        payload = good_payload()
        payload["timestamp_utc"] = (NOW - timedelta(minutes=10)).isoformat()
        frame = validate_telemetry(payload, "gateway", received_at=NOW)
        self.assertFalse(frame.valid)
        self.assertIn("telemetry is stale", frame.errors)

    def test_rejects_future_timestamp(self):
        payload = good_payload()
        payload["timestamp_utc"] = (NOW + timedelta(minutes=2)).isoformat()
        frame = validate_telemetry(payload, "gateway", received_at=NOW)
        self.assertIn("telemetry timestamp is too far in the future", frame.errors)

    def test_rejects_timestamp_without_timezone(self):
        payload = good_payload()
        payload["timestamp_utc"] = "2026-10-23T05:00:00"
        frame = validate_telemetry(payload, "gateway", received_at=NOW)
        self.assertFalse(frame.valid)
        self.assertTrue(any("timezone" in e for e in frame.errors))

    def test_rejects_missing_required_sensor_field(self):
        payload = good_payload()
        del payload["water_demand_m3"]
        frame = validate_telemetry(payload, "gateway", received_at=NOW)
        self.assertIn("missing required field: water_demand_m3", frame.errors)

    def test_rejects_nonfinite_boolean_and_negative_measurements(self):
        for bad in (float("nan"), float("inf"), True, -0.1, "not-a-number"):
            with self.subTest(value=bad):
                payload = good_payload()
                payload["renewable_surplus_kw"] = bad
                frame = validate_telemetry(payload, "gateway", received_at=NOW)
                self.assertFalse(frame.valid)

    def test_rejects_bad_device_quality_flag(self):
        payload = good_payload()
        payload["quality_flag"] = "sensor_fault"
        self.assertFalse(validate_telemetry(payload, "gateway", received_at=NOW).valid)

    def test_reports_missing_device_identity_as_warning(self):
        payload = good_payload()
        del payload["device_id"]
        frame = validate_telemetry(payload, "gateway", received_at=NOW)
        self.assertTrue(frame.valid)
        self.assertTrue(any("device_id" in warning for warning in frame.warnings))

    def test_rejects_naive_receive_time(self):
        with self.assertRaisesRegex(ValueError, "received_at must be timezone-aware"):
            validate_telemetry(good_payload(), "gateway", received_at=datetime(2026, 10, 23))


class TestControlAuthorization(unittest.TestCase):
    def setUp(self):
        self.request = ControlRequest(
            command="ro_power_setpoint_kw", requested_value=12.0,
            minimum=0.0, maximum=20.0, max_change_per_step=5.0,
        )
        self.safe = SafetyContext(
            telemetry_valid=True, write_enabled=True, operator_confirmed=True,
            previous_value=10.0,
        )

    def test_default_context_is_fail_closed(self):
        decision = authorize_control(self.request, SafetyContext())
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.approved_value)
        self.assertIn("physical write path is disabled (recommendation-only mode)", decision.reasons)

    def test_all_interlocks_satisfied_allows_authorization_only(self):
        decision = authorize_control(self.request, self.safe)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.approved_value, 12.0)
        self.assertFalse(decision.as_dict()["physical_write_performed"])

    def test_emergency_stop_denies(self):
        context = SafetyContext(**{**self.safe.__dict__, "emergency_stop": True})
        decision = authorize_control(self.request, context)
        self.assertFalse(decision.allowed)
        self.assertIn("emergency stop is active", decision.reasons)

    def test_manual_override_denies(self):
        context = SafetyContext(**{**self.safe.__dict__, "manual_override": True})
        self.assertFalse(authorize_control(self.request, context).allowed)

    def test_requires_explicit_operator_confirmation(self):
        context = SafetyContext(**{**self.safe.__dict__, "operator_confirmed": False})
        self.assertFalse(authorize_control(self.request, context).allowed)

    def test_rejects_out_of_range_setpoint(self):
        request = ControlRequest("ro_power", 30.0, 0.0, 20.0)
        decision = authorize_control(request, self.safe)
        self.assertFalse(decision.allowed)
        self.assertIn("requested value is outside configured operating limits", decision.reasons)

    def test_rejects_ramp_limit_violation(self):
        request = ControlRequest("ro_power", 18.0, 0.0, 20.0, max_change_per_step=3.0)
        decision = authorize_control(request, self.safe)
        self.assertFalse(decision.allowed)
        self.assertIn("requested change exceeds configured ramp limit", decision.reasons)

    def test_rejects_missing_previous_value_for_ramp_check(self):
        request = ControlRequest("ro_power", 12.0, 0.0, 20.0, max_change_per_step=3.0)
        context = SafetyContext(telemetry_valid=True, write_enabled=True, operator_confirmed=True)
        self.assertFalse(authorize_control(request, context).allowed)

    def test_recommendation_never_claims_hardware_write(self):
        record = build_recommendation(
            "ro_power_setpoint_kw", 12.0, "kW", "renewable surplus available",
            "rolling_dispatch", "islandos-dev", created_at=NOW,
        )
        self.assertEqual(record["kind"], "recommendation_only")
        self.assertTrue(record["operator_action_required"])
        self.assertFalse(record["physical_write_performed"])

    def test_rejects_nonfinite_recommendation(self):
        with self.assertRaisesRegex(ValueError, "requested_value must be finite"):
            build_recommendation("ro_power", float("nan"), "kW", "test", "test", "v1")


if __name__ == "__main__":
    unittest.main()
