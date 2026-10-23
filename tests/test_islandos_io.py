"""Tests for fail-closed telemetry and hardware-control safety boundary."""
import unittest
import json
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone

from islandos_io import (
    ControlRequest,
    SafetyContext,
    authorize_control,
    build_dispatch_input_rows,
    build_recommendation,
    load_device_mapping,
    apply_device_mapping,
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


class TestDeviceMappingContract(unittest.TestCase):
    def valid_mapping(self):
        return {
            "schema_version": 1,
            "fields": {
                "timestamp_utc": {"source_key": "ts", "source_unit": "ISO-8601", "canonical_unit": "ISO-8601"},
                "renewable_surplus_kw": {"source_key": "solar_w", "source_unit": "W", "canonical_unit": "kW", "scale": 0.001},
                "water_demand_m3": {"source_key": "water_l", "source_unit": "L", "canonical_unit": "m3", "scale": 0.001},
                "cooling_demand_kw_th": {"source_key": "cooling_kw", "source_unit": "kW_th", "canonical_unit": "kW_th"},
            },
        }

    def test_loads_explicit_unit_mapping_and_converts_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(self.valid_mapping()), encoding="utf-8")
            mapping = load_device_mapping(str(path))
        payload = apply_device_mapping({
            "ts": "2026-10-23T05:00:00Z",
            "solar_w": 42000,
            "water_l": 1250,
            "cooling_kw": 8,
        }, mapping)
        self.assertEqual(payload["renewable_surplus_kw"], 42.0)
        self.assertEqual(payload["water_demand_m3"], 1.25)
        self.assertEqual(payload["timestamp_utc"], "2026-10-23T05:00:00Z")

    def test_rejects_mapping_without_required_fields(self):
        mapping = self.valid_mapping()
        del mapping["fields"]["water_demand_m3"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required canonical fields"):
                load_device_mapping(str(path))

    def test_rejects_missing_or_wrong_canonical_units(self):
        for mutate in ("missing", "wrong"):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as tmp:
                mapping = self.valid_mapping()
                if mutate == "missing":
                    del mapping["fields"]["water_demand_m3"]["canonical_unit"]
                else:
                    mapping["fields"]["water_demand_m3"]["canonical_unit"] = "L"
                path = Path(tmp) / "mapping.json"
                path.write_text(json.dumps(mapping), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "canonical_unit"):
                    load_device_mapping(str(path))

    def test_rejects_duplicate_source_key_and_timestamp_scaling(self):
        mapping = self.valid_mapping()
        mapping["fields"]["water_demand_m3"]["source_key"] = "solar_w"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only one canonical field"):
                load_device_mapping(str(path))
        mapping = self.valid_mapping()
        mapping["fields"]["timestamp_utc"]["scale"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text(json.dumps(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "timestamp_utc cannot"):
                load_device_mapping(str(path))


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

    def test_accepts_optional_forecasts_and_rejects_invalid_optional_values(self):
        payload = good_payload()
        payload["forecast_surplus_kw"] = 35.0
        payload["forecast_water_demand_m3"] = 4.5
        frame = validate_telemetry(payload, "gateway", received_at=NOW)
        self.assertTrue(frame.valid)
        self.assertEqual(frame.values["forecast_surplus_kw"], 35.0)
        self.assertEqual(frame.values["forecast_water_demand_m3"], 4.5)
        payload["forecast_surplus_kw"] = float("nan")
        invalid = validate_telemetry(payload, "gateway", received_at=NOW)
        self.assertFalse(invalid.valid)
        self.assertTrue(any("forecast_surplus_kw" in error for error in invalid.errors))

    def _valid_dispatch_records(self):
        records = []
        for index, surplus in enumerate((20.0, 35.0, 15.0)):
            stamp = NOW + timedelta(hours=index)
            records.append({
                "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
                "valid": True,
                "values": {
                    "renewable_surplus_kw": surplus,
                    "water_demand_m3": 4.0 + index,
                    "cooling_demand_kw_th": 7.0 + index,
                },
            })
        return records

    def test_dispatch_input_uses_previous_value_persistence_baseline(self):
        rows = build_dispatch_input_rows(self._valid_dispatch_records())
        self.assertEqual([row["forecast_surplus_kw"] for row in rows], [20.0, 20.0, 35.0])
        self.assertEqual([row["forecast_water_demand_m3"] for row in rows], [4.0, 4.0, 5.0])
        self.assertEqual(rows[1]["actual_surplus_kw"], 35.0)

    def test_dispatch_input_preserves_supplied_forecasts(self):
        records = self._valid_dispatch_records()
        records[1]["values"]["forecast_surplus_kw"] = 29.0
        records[1]["values"]["forecast_water_demand_m3"] = 4.8
        rows = build_dispatch_input_rows(records)
        self.assertEqual(rows[1]["forecast_surplus_kw"], 29.0)
        self.assertEqual(rows[1]["forecast_water_demand_m3"], 4.8)

    def test_dispatch_input_rejects_irregular_intervals_and_bad_rows(self):
        records = self._valid_dispatch_records()
        records[2]["timestamp_utc"] = (NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
        with self.assertRaisesRegex(ValueError, "exactly one-hour intervals"):
            build_dispatch_input_rows(records)
        records = self._valid_dispatch_records()
        records[1]["valid"] = False
        with self.assertRaisesRegex(ValueError, "all telemetry rows must pass validation"):
            build_dispatch_input_rows(records)

    def test_dispatch_input_requires_at_least_two_rows(self):
        with self.assertRaisesRegex(ValueError, "at least two hourly telemetry rows"):
            build_dispatch_input_rows(self._valid_dispatch_records()[:1])

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

    def test_malformed_request_values_are_denied_without_exception(self):
        for requested, minimum, maximum in (("bad", 0.0, 20.0), (float("nan"), 0.0, 20.0), (12.0, 30.0, 20.0)):
            with self.subTest(requested=requested, minimum=minimum, maximum=maximum):
                request = ControlRequest("ro_power", requested, minimum, maximum)
                decision = authorize_control(request, self.safe)
                self.assertFalse(decision.allowed)
                self.assertIsNone(decision.approved_value)

    def test_invalid_ramp_limit_is_denied(self):
        request = ControlRequest("ro_power", 12.0, 0.0, 20.0, max_change_per_step=float("nan"))
        decision = authorize_control(request, self.safe)
        self.assertFalse(decision.allowed)
        self.assertIn("maximum change per step must be finite and non-negative", decision.reasons)

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
