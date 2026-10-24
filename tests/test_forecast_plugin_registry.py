"""Contract tests for dependency-free plug-in water-demand forecast models."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.forecasting import (
    ForecastModelRegistry,
    ForecastRequest,
    WaterObservation,
)


class ConstantPlugin:
    model_id = "constant"
    version = "1.0"

    def __init__(self, predictions):
        self.predictions = predictions

    def predict(self, history, target_timestamps):
        return self.predictions


class TestForecastPluginRegistry(unittest.TestCase):
    def setUp(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.history = tuple(
            WaterObservation(start + timedelta(hours=i), float(i + 1))
            for i in range(48)
        )
        self.targets = tuple(
            start + timedelta(hours=48 + i) for i in range(3)
        )
        self.request = ForecastRequest(self.history, self.targets)

    def test_registers_and_runs_a_plugin_with_provenance(self):
        registry = ForecastModelRegistry()
        registry.register(ConstantPlugin([12, 13, 14]))
        result = registry.forecast("constant", self.request)
        self.assertEqual(result.model_id, "constant")
        self.assertEqual(result.model_version, "1.0")
        self.assertEqual([p.timestamp for p in result.points], list(self.targets))
        self.assertEqual([p.predicted_demand_m3 for p in result.points], [12.0, 13.0, 14.0])
        self.assertEqual(len(result.input_history_sha256), 64)
        self.assertEqual(registry.available_models(), (("constant", "1.0"),))

    def test_rejects_duplicate_plugin_id_and_unknown_model(self):
        registry = ForecastModelRegistry()
        registry.register(ConstantPlugin([1, 2, 3]))
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(ConstantPlugin([1, 2, 3]))
        with self.assertRaisesRegex(KeyError, "Unknown forecast plugin"):
            registry.forecast("missing", self.request)

    def test_rejects_wrong_output_length_and_invalid_predictions(self):
        registry = ForecastModelRegistry()
        registry.register(ConstantPlugin([1, 2]))
        with self.assertRaisesRegex(ValueError, "returned 2 predictions"):
            registry.forecast("constant", self.request)
        for invalid in ([1, -1, 3], [1, float("nan"), 3], [1, float("inf"), 3], [1, True, 3]):
            registry = ForecastModelRegistry()
            registry.register(ConstantPlugin(invalid))
            with self.assertRaisesRegex(ValueError, "predictions|prediction"):
                registry.forecast("constant", self.request)

    def test_rejects_naive_timestamps_and_gaps(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            WaterObservation(datetime(2026, 1, 1), 1.0)
        with self.assertRaisesRegex(ValueError, "hourly data"):
            ForecastRequest(
                (self.history[0], self.history[2]),
                self.targets,
            )
        with self.assertRaisesRegex(ValueError, "exactly one hour"):
            ForecastRequest(
                self.history,
                (self.history[-1].timestamp + timedelta(hours=2),),
            )
        with self.assertRaisesRegex(ValueError, "exactly one hour"):
            ForecastRequest(self.history, (self.history[-1].timestamp,))
        with self.assertRaisesRegex(ValueError, "exactly one hour"):
            ForecastRequest(
                self.history,
                (self.history[-1].timestamp + timedelta(minutes=30),),
            )

    def test_rejects_invalid_observed_demand(self):
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            WaterObservation(self.history[0].timestamp, -1.0)
        with self.assertRaisesRegex(ValueError, "numeric, finite and non-negative"):
            WaterObservation(self.history[0].timestamp, float("nan"))
        with self.assertRaisesRegex(ValueError, "numeric, finite and non-negative"):
            WaterObservation(self.history[0].timestamp, True)
        with self.assertRaisesRegex(ValueError, "numeric, finite and non-negative"):
            WaterObservation(self.history[0].timestamp, "12")


if __name__ == "__main__":
    unittest.main()
