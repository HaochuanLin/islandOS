# Stages 6–9 engineering foundation

**Status:** first implementation increment; not a field-validated release.  
**Mainline at branch creation:** current `main` on 2026-11-14.

This increment adds explicit contracts around existing IslandOS capabilities. It
does not delete legacy modules or claim that every UI page has been migrated.

## Stage 6 — canonical core boundary

- `islandos_core.canonical_runtime.CanonicalForecastRuntime` is the supported
  facade for aligned multi-signal forecasts entering planning.
- It delegates model execution to the existing `ForecastService`, validates
  required signal IDs, units, timestamps, bounds and SHA-256 provenance, and
  returns immutable planning arrays.
- Existing prediction engines and older forecast contracts remain in place for
  compatibility. Migration of every page and adapter is a subsequent task.
- No algorithm is silently promoted: statistical baseline models remain
  baselines, and independent per-signal forecasting is not multivariate learning.

## Stage 7 — forecast and optimization evidence

- `forecast_evaluation_report.evaluate_realized_forecast` scores predictions
  against caller-supplied realized observations using MAE, RMSE, bias, WAPE,
  interval coverage and mean interval width.
- Missing timestamps and invalid numeric values fail closed.
- This is an evaluation primitive, not a completed public-data backtest. Real
  OPSD download/replay and site-specific validation remain outstanding; see PR
  #250 and the forecast benchmarking documentation.
- Dispatch feasibility and economics must continue to be assessed separately
  from forecast accuracy.

## Stage 8 — device and data integration boundary

- `telemetry_adapter_contract.normalize_telemetry_batch` defines a versioned,
  read-only normalized telemetry batch with unit, quality, freshness,
  completeness, duplicate and provenance checks.
- Existing gateway, device mapping and signal modules remain the protocol and
  transport integration points.
- This increment does not add vendor-specific hardware drivers, PLC/SCADA
  writes, or prove sensor calibration. Physical device connectivity remains
  unverified until equipment and site access exist.

## Stage 9 — safety and reliability boundary

- `control_boundary.build_human_review_envelope` creates a hashed,
  human-reviewable decision record.
- Operational authorization, device writes and command generation are
  hard-coded false/null in this decision-support boundary.
- Existing `safety_governance`, `production_preflight`, `shadow_mode`,
  `operational_state`, and gateway validation remain separate controls and
  must be composed and independently reviewed before any pilot.
- Passing software tests is not a safety certification. Site-specific risk
  assessment, independent interlocks, emergency stop, rollback and qualified
  approval remain mandatory.

## Verification

The new tests cover the canonical forecast contract, realized-data scoring,
telemetry normalization and non-actuating decision envelope. Repository CI
must pass before merge. Tests using fixtures or synthetic data are software
contract tests only, not evidence of real-world model performance.
