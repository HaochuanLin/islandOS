# Stage 3 — Unified evidence-gated prediction engine

## Purpose

Stage 3 turns the existing per-signal prediction engine into a reusable
multi-signal forecasting service. It is designed to provide aligned forecasts
to the downstream resource-coordination optimizer while preserving the source
history, selected model identity, backtest evidence and uncertainty metadata.

The service forecasts each signal independently. It does **not** claim to learn
cross-signal causal relationships or multivariate dynamics.

## Included capabilities

- One common request contract for timestamped signals such as site load,
  renewable generation, tariff and water demand.
- A forecast bundle requires the same UTC-normalized historical timestamps and
  target timestamps across all included signals.
- Every signal retains its own unit, model ID/version, input-history SHA-256,
  rolling-origin backtest metrics and uncertainty bands.
- Default transparent candidates include persistence, seasonal-naive,
  recent-mean and linear-trend models. Candidate evaluation reports aggregate
  MAE, RMSE, signed bias (prediction minus actual), WAPE where defined, and
  per-fold MAE/RMSE/bias with training and validation sample counts.
- Each horizon score uses only complete chronological validation blocks;
  an incomplete trailing block is excluded rather than mixed into a shorter horizon.
- Forecasting is fail-closed: if one signal cannot be forecast, no partial
  bundle is returned to the optimizer.
- Explicit model selection is accepted only when that candidate passes the
  signal's backtest and output contract.
- Uncertainty bands use an empirical absolute-error quantile over chronological
  rolling-origin replay residuals. Candidate selection and error-band estimation
  currently reuse the same replay history, so the bands are descriptive rather
  than independently calibrated; they do not guarantee nominal statistical
  coverage.
- The bundle has a deterministic SHA-256 digest over its aligned timestamps,
  signal units, model identities, input digests and forecast points.

## Python usage

```python
from datetime import datetime, timedelta, timezone

from islandos_core.forecast_service import ForecastBundleRequest, ForecastService
from islandos_core.prediction_engine import ForecastRequest, SignalObservation

start = datetime(2026, 1, 1, tzinfo=timezone.utc)
history = tuple(
    SignalObservation(start + timedelta(hours=i), float(i % 24))
    for i in range(96)
)
targets = tuple(
    start + timedelta(hours=96 + i)
    for i in range(24)
)

load = ForecastRequest("site_load", "kW", history, targets)
solar = ForecastRequest("pv_generation", "kW", history, targets)

bundle = ForecastService().forecast_bundle(
    ForecastBundleRequest((load, solar)),
    initial_history=48,
    backtest_horizon=24,
    season_length=24,
    confidence_level=0.90,
)

print(bundle.bundle_sha256)
print(bundle.forecasts["site_load"].backtest.mae)
```

## Release and safety boundaries

- Built-in models remain transparent statistical baselines; no trained site
  model or site-specific accuracy claim is implied.
- No missing-data interpolation, automatic unit conversion or timestamp repair
  is performed in this service. Stage 2 onboarding must establish valid,
  normalized, regular sampling before prediction.
- Signals are forecast independently; price, load, renewable generation,
  storage state and water demand are not assumed to be causally linked.
- A forecast bundle is decision-support input only. It cannot issue PLC,
  inverter, battery, generator or other equipment commands.
- A passing synthetic test suite establishes software behavior, not field
  accuracy, sensor calibration or operational suitability.

## Validation

Run:

```bash
pytest -q tests/test_prediction_engine.py tests/test_forecast_service.py
```

The tests cover deterministic bundle digests, UTC-aligned histories and target
grids, duplicate signal rejection, unknown model mappings, invalid candidate
outputs, explicit model eligibility, persistence baseline behavior, fold-level
signed bias and empirical error-band metadata. The OPSD CLI can evaluate this canonical engine separately
from the legacy Phase 2 Ridge comparison.
