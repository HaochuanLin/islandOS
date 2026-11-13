# Phase 2 follow-up — rolling-origin validation utilities

This add-on introduces reusable evaluation primitives in
`islandos_core/forecast_validation.py`. It does not silently change the
selection behavior of the existing forecast engine.

## Site-local calendar features

`site_local_calendar_features(timestamp, site_timezone)` converts an
aware timestamp to an IANA timezone using the standard library `zoneinfo`,
then returns cyclic hour-of-day and day-of-week features. This handles
UTC offsets and daylight-saving transitions using the timezone database.
The forecast service can continue to store and return timestamps in UTC;
the site timezone is used only when deriving calendar features.

## Expanding-window evaluation

`evaluate_expanding_window(...)` evaluates named forecaster callbacks on
identical, chronological validation blocks. Each callback receives only
its training values and the timestamps of the future validation block;
validation actuals are withheld. The default is four expanding folds, each
with a 24-hour validation block and at least 72 training observations.

The helper returns per-fold MAE, RMSE, signed bias, and mean MAE for each
candidate/baseline. It intentionally does not automatically promote a
model: production selection should require consistent baseline wins across
representative, site-authorized data and stress periods.

## Current boundary

These utilities remain separate from automatic model promotion, but the built-in candidate models can now be evaluated directly through `evaluate_signal_rolling(...)` in `islandos_core/forecast_engine.py`. That helper evaluates the same persistence, seasonal-naive, and ridge implementations used by `forecast_signals`, refitting ridge independently inside each training fold and recursively forecasting each validation block. It returns per-fold MAE, RMSE, and signed bias for each horizon. The production `forecast_signals` selection gate is deliberately unchanged: a rolling score report is evidence for model review, not an automatic deployment decision. These results do not establish site accuracy.

## Horizon-specific validation

The module also exposes `evaluate_horizon_windows(...)`, which runs an independent expanding-window evaluation for each requested horizon (1–168 hours). This keeps short-horizon and long-horizon errors separate instead of reporting one blended score. The default horizon set is 1, 6, 12, 24, 48, and 168 hours; each horizon requires enough history for its own requested number of folds. Model callbacks still receive only training values and future timestamps.

The `phase2_opsd_backtest.py` CLI can opt into this evaluation with `--rolling-validation` and choose horizons with `--rolling-horizons 1 6 24 168`. Four folds are evaluated per horizon with at least 72 training observations in the first fold. The CLI reports each model's mean MAE and individual fold MAE/RMSE/bias. The standard forecast selection remains holdout-gated until a separate policy change is justified by representative data.
