"""Minimal runnable example of a replaceable water-demand forecast plugin."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Sequence

# Make the repository root importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from islandos_core.forecasting import (
    ForecastModelRegistry,
    ForecastRequest,
    WaterObservation,
)


class TrailingDayMean:
    """Example only: predict each requested hour using the latest 24-hour mean."""

    model_id = "trailing-day-mean"
    version = "1.0.0"

    def predict(
        self,
        history: Sequence[WaterObservation],
        target_timestamps: Sequence[datetime],
    ) -> Sequence[float]:
        if len(history) < 24:
            raise ValueError("TrailingDayMean requires at least 24 hourly observations")
        estimate = mean(point.demand_m3 for point in history[-24:])
        return [estimate] * len(target_timestamps)


def main() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = tuple(
        WaterObservation(start + timedelta(hours=index), 20.0 + index % 8)
        for index in range(48)
    )
    targets = tuple(start + timedelta(hours=48 + index) for index in range(6))
    request = ForecastRequest(history=history, target_timestamps=targets)

    registry = ForecastModelRegistry()
    registry.register(TrailingDayMean())
    result = registry.forecast("trailing-day-mean", request)
    print(json.dumps({
        "model_id": result.model_id,
        "model_version": result.model_version,
        "input_history_sha256": result.input_history_sha256,
        "forecast": [
            {
                "timestamp": point.timestamp.isoformat(),
                "predicted_demand_m3": point.predicted_demand_m3,
            }
            for point in result.points
        ],
        "interpretation": "synthetic interface example only; not a trained model or site forecast",
    }, indent=2))


if __name__ == "__main__":
    main()
