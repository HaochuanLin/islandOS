# Phase C — Generic prediction engine

## Purpose

Phase C establishes a common, auditable prediction interface across energy and resource signals. It is a model orchestration layer, not a claim that IslandOS already has a trained universal AI model.

The first implementation lives in `islandos_core/prediction_engine.py` and is independent of Streamlit.

## Current capabilities

- Timezone-aware, regular-interval observations and forecast targets.
- Explicit signal ID, unit and non-negative/signed-value contract (so electricity prices may be negative while load/PV/water demand may not).
- Pluggable forecast candidates with immutable registered model ID/version.
- Built-in seasonal-naive, recent-mean and linear-trend candidates.
- Expanding-history, rolling-origin candidate replay. Every fold predicts only from observations before that fold.
- Candidate ranking by MAE, then RMSE, then stable model ID.
- Input-history SHA-256 in the forecast result.
- Empirical symmetric error bands calibrated from rolling-origin absolute residuals.
- Candidate outputs that violate numeric, finite-value or signal-domain contracts are ineligible; values are not silently clipped or repaired.

## How to use

```python
from datetime import datetime, timedelta, timezone
from islandos_core.prediction_engine import (
    ForecastRequest, PredictionEngine, SignalObservation,
)

start = datetime(2026, 1, 1, tzinfo=timezone.utc)
values = [float(i % 24) for i in range(96)]
history = tuple(
    SignalObservation(start + timedelta(hours=i), value)
    for i, value in enumerate(values)
)
targets = tuple(
    start + timedelta(hours=96 + i)
    for i in range(24)
)
request = ForecastRequest(
    signal_id="site_load",
    unit="kW",
    history=history,
    target_timestamps=targets,
    non_negative=True,
)
result = PredictionEngine().forecast(request, initial_history=48)
```

External ML/statistical candidates can implement the `ForecastCandidate` protocol and be registered with `PredictionEngine.register()`. Candidate identity and version are retained in result metadata. Production promotion should require stronger evidence than passing a unit test.

## Evaluation and uncertainty boundaries

- The default selector minimizes MAE on supplied chronological replay folds. It does not use future values in a fold.
- Error bands are empirical residual quantiles from the same rolling-origin replay. They are descriptive calibration bands, not guaranteed coverage intervals.
- Model selection is data-dependent. A short or synthetic history may select a weak candidate; callers must inspect fold count, sample count and metrics.
- No site-specific accuracy is claimed without customer/site history, baseline comparison, drift monitoring and out-of-sample validation.
- No training pipeline, automatic model deployment, cloud model registry, or live-control write path is introduced by this phase.
- Existing water-demand plugin contracts and tariff-specific forecasting remain specialized domain interfaces. The generic engine is an orchestration foundation; adapters and unified customer workflows remain to be completed.

## Next integration work

1. Add adapters from validated customer onboarding records to generic signal observations.
2. Connect tariff, load, PV, wind and water-demand forecasts to one run manifest.
3. Add candidate-specific baselines and per-signal backtest reports to the customer dashboard.
4. Add model versioning, drift checks and evidence-gated candidate promotion.
5. Keep optimization as a downstream consumer of forecasts, never as an implicit feedback controller.
