"""Run a reproducible synthetic demonstration of the Phase 2 forecast engine.

The generated signals are illustrative software-test data, not measurements
from an island, utility, customer, or operating plant.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from islandos_core.forecast_engine import forecast_signals


def main() -> None:
    hours = 240
    timestamps = [
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(hours)
    ]
    history = {
        "pv_power": [
            max(0.0, 35.0 * math.sin(math.pi * ((i % 24) - 6) / 12.0))
            * (0.90 + 0.08 * math.sin((i // 24) * 0.7))
            for i in range(hours)
        ],
        "wind_power": [
            14.0 + 3.5 * math.sin(2.0 * math.pi * i / 24.0 + 0.8)
            + 1.5 * math.sin(2.0 * math.pi * i / 72.0)
            for i in range(hours)
        ],
        "essential_load": [
            18.0 + 2.0 * math.sin(2.0 * math.pi * ((i % 24) - 8) / 24.0)
            + 0.5 * math.sin((i // 24) * 0.4)
            for i in range(hours)
        ],
        "water_demand": [
            0.45 + 0.06 * math.sin(2.0 * math.pi * ((i % 24) - 6) / 24.0)
            + 0.02 * math.sin((i // 24) * 0.5)
            for i in range(hours)
        ],
        "electricity_price": [
            -0.02 if i % 24 < 5 else (0.08 if i % 24 < 7 else 0.18)
            for i in range(hours)
        ],
    }
    result = forecast_signals(
        timestamps=timestamps,
        history=history,
        units={
            "pv_power": "kW",
            "wind_power": "kW",
            "essential_load": "kW",
            "water_demand": "m3/h",
            "electricity_price": "currency/kWh",
        },
        horizon=24,
        non_negative_signals=("pv_power", "wind_power", "essential_load", "water_demand"),
    )
    report = {
        "data_provenance": "Synthetic demo data — not measured site data",
        "input_history_sha256": result.input_history_sha256,
        "forecast_horizon_hours": 24,
        "signals": {
            name: {
                "selected_model": forecast.model_id,
                "holdout_mae": forecast.holdout_metrics.mae,
                "holdout_rmse": forecast.holdout_metrics.rmse,
                "holdout_bias": forecast.holdout_metrics.bias_predicted_minus_actual,
                "beats_baseline": forecast.selected_model_beats_baseline,
                "first_forecast_utc": forecast.points[0].timestamp.isoformat(),
                "first_forecast_value": forecast.points[0].predicted,
                "unit": forecast.unit,
            }
            for name, forecast in result.forecasts.items()
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
