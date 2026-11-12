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

These utilities are implemented and unit-tested as standalone primitives.
The current `forecast_signals` API still uses its original single holdout
selection and UTC calendar features until a separately reviewed integration
change wires these helpers into model fitting and records the selected site
timezone in forecast provenance. They do not establish site accuracy.
