"""Tests for versioned, JSON-compatible decision audit records."""
from datetime import datetime, timezone
import json
import unittest

from islandos_core.audit import build_decision_audit_record
from islandos_core.configuration import SiteConfiguration
from islandos_core.decision import recommend_ro_screening
from islandos_core.signals import SignalReading


NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
CONFIG = SiteConfiguration(
    site_id="synthetic-site",
    water_demand_m3_per_day=100,
    ro_capacity_m3_per_day=120,
    energy_price_per_kwh=0.18,
    ro_specific_energy_kwh_per_m3=3.5,
    storage_capacity_m3=50,
    initial_storage_m3=10,
)


def reading(signal_id, value, unit):
    return SignalReading(signal_id, value, unit, NOW, "offline-simulation", "good")


class DecisionAuditRecordTests(unittest.TestCase):
    def setUp(self):
        self.inputs = [
            reading("renewable_surplus_kw", 20, "kW"),
            reading("water_inventory_m3", 5, "m3"),
        ]
        self.recommendation = recommend_ro_screening(
            CONFIG, renewable_surplus=self.inputs[0], water_inventory=self.inputs[1]
        )

    def test_record_round_trips_as_json_and_keeps_traceability(self):
        record = build_decision_audit_record(
            config=CONFIG,
            inputs=self.inputs,
            recommendation=self.recommendation,
            created_at=NOW,
            run_id="synthetic-run-001",
            input_mode="offline_simulation",
        )
        decoded = json.loads(json.dumps(record))
        self.assertEqual(decoded["audit_schema_version"], "1.0")
        self.assertEqual(decoded["site_id"], "synthetic-site")
        self.assertEqual(decoded["configuration"]["water_demand_m3_per_day"], 100)
        self.assertEqual(
            [item["signal_id"] for item in decoded["inputs"]],
            ["renewable_surplus_kw", "water_inventory_m3"],
        )
        self.assertEqual(
            decoded["decision"]["recommendation"]["action"],
            self.recommendation.action,
        )
        self.assertTrue(decoded["safety_boundary"]["read_only"])
        self.assertTrue(decoded["safety_boundary"]["requires_human_review"])
        self.assertIsNone(decoded["safety_boundary"]["control_command"])

    def test_naive_created_at_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_decision_audit_record(
                config=CONFIG,
                inputs=self.inputs,
                recommendation=self.recommendation,
                created_at=datetime(2026, 10, 23, 12, 0),
                run_id="run-1",
                input_mode="offline_simulation",
            )

    def test_missing_metadata_or_inputs_is_rejected(self):
        for kwargs, expected in [
            ({"run_id": " ", "input_mode": "offline"}, "run_id"),
            ({"run_id": "run-1", "input_mode": " "}, "input_mode"),
            ({"run_id": "run-1", "input_mode": "offline", "inputs": []}, "at least one"),
        ]:
            params = {
                "config": CONFIG,
                "inputs": self.inputs,
                "recommendation": self.recommendation,
                "created_at": NOW,
                "run_id": "run-1",
                "input_mode": "offline_simulation",
            }
            params.update(kwargs)
            with self.assertRaisesRegex(ValueError, expected):
                build_decision_audit_record(**params)

    def test_duplicate_signal_ids_are_rejected(self):
        duplicate = [self.inputs[0], reading("renewable_surplus_kw", 21, "kW")]
        with self.assertRaisesRegex(ValueError, "unique"):
            build_decision_audit_record(
                config=CONFIG,
                inputs=duplicate,
                recommendation=self.recommendation,
                created_at=NOW,
                run_id="run-1",
                input_mode="offline_simulation",
            )


if __name__ == "__main__":
    unittest.main()
