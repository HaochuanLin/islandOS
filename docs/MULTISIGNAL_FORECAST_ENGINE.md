# Unified multi-signal forecasting engine

## Purpose and scope

`islandos_core/multisignal_forecasting.py` provides one dependency-free contract for renewable generation and demand signals. PV power, wind power, essential electrical load, and water demand are represented as separate named signals with explicit units and timestamps. A plugin can be reused across signals without changing the dispatch simulator.

This is a model integration and evaluation boundary, not a claim that every signal already has a trained AI model. The seasonal-naive baseline and optional trained weather/water experiments remain separate candidates. Models are not automatically selected, promoted, or connected to live equipment.

## Shared runtime contract

- `SignalObservation`: timezone-aware timestamp, stable signal ID, finite non-negative value, and explicit unit.
- `SignalForecastRequest`: one signal and unit, continuous history, future target timestamps, and an explicit cadence in seconds.
- `SignalForecastPlugin`: `model_id`, `version`, and `predict(history, target_timestamps)`.
- `SignalForecastRegistry`: validates plugin identity, output length, finite/non-negative predictions, and records a SHA-256 digest of the exact history passed to the model.
- `SignalForecastResult`: keeps signal ID, unit, cadence, model identity, input digest, and timestamped point forecasts together.

Cadence is explicit rather than hard-coded to one hour. The contract supports sub-hourly, hourly, and daily series when each history and target sequence is continuous at the declared cadence. It does not resample data or convert units: callers must normalize units and timestamps before creating a request. Each request forecasts one signal; call the same registry separately for PV, wind, and load.

## Prediction intervals

Intervals are optional. Supply at least 20 timestamped `CalibrationResidual` values from prior out-of-sample predictions to `registry.forecast(..., calibration_residuals=..., interval_coverage=0.90)`. Every calibration timestamp must precede the first forecast target and the residuals must be chronologically ordered.

The engine uses a finite-sample split-conformal absolute-residual quantile and returns non-negative lower bounds and upper bounds. Without a calibration set, lower and upper bounds remain `None`; the engine never invents confidence bounds. The nominal coverage is a calibration target, not a guarantee: time-series dependence, distribution shift, sparse regimes, and site changes can reduce realized coverage. Calibration errors must be generated without using the evaluation targets.

## Rolling-origin comparison

`rolling_origin_backtest` compares a plugin with persistence and seasonal-naive baselines. Every test prediction is generated using only observations before its timestamp. Plugin and persistence metrics use the same timestamps; seasonal-naive metrics are reported on their available lag window, with a matching plugin metric on that exact window.

The report includes MAE, RMSE, bias, WAPE (null when actual total is zero), underforecast rate, skill versus persistence, per-row history digests, and an evaluation-series digest. A positive skill score means lower MAE than persistence; a negative score means worse. It is not a model promotion decision.

## Example

```python
from islandos_core.multisignal_forecasting import (
    SignalForecastRegistry, SignalForecastRequest, SignalObservation,
)

# Build timestamp-aligned, unit-normalized observations for one signal.
history = tuple(
    SignalObservation(timestamp, "pv_power", value_kw, "kW")
    for timestamp, value_kw in pv_history
)
request = SignalForecastRequest(
    signal_id="pv_power",
    unit="kW",
    history=history,
    target_timestamps=next_hour_timestamps,
    cadence_seconds=3600,
)
registry = SignalForecastRegistry()
registry.register(your_trusted_plugin)
result = registry.forecast(your_trusted_plugin.model_id, request)
```

Use the same contract for `wind_power` and `essential_load`, changing the signal ID and retaining the correct unit. Only load trusted plugin code; Python plugins execute in the host process.

## Tests and evidence limits

Run:

```bash
python -m pytest tests/test_multisignal_forecasting.py tests/test_forecast_plugin_registry.py tests/test_scenario_forecasting.py
```

The tests cover PV/wind/load signal reuse, sub-hourly/hourly/daily cadence, malformed timestamps and gaps, non-negative physical signals, calibrated intervals, and rolling-origin comparisons. Test fixtures are synthetic. They demonstrate software contract behavior, not forecast accuracy, field validation, or safe control.

## Forecast-to-dispatch boundary

Use `forecast_values_for_dispatch` to extract point, lower, or upper series for a downstream simulator. It verifies signal ID, unit label, and exact target timestamp alignment, and refuses lower/upper extraction when no calibrated interval exists. It returns values only; the caller remains responsible for selecting the appropriate conservative direction (for example, lower renewable generation or upper load), passing them to the physical model, and preserving the realized series separately for outcome scoring. No unit conversion or live command is performed.
