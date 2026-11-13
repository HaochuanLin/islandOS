# Stage D — Generic forecast-led resource coordination

## Delivered path

Stage D connects the generic prediction engine to the existing joint battery/diesel dispatch optimizer and exposes that end-to-end path in the Streamlit application at `pages/06_Forecast_Led_Joint_Resource_Optimizer.py`.

1. Accept aligned hourly PV, wind, essential-load, and tariff histories from the existing strict customer CSV schema, or use explicitly labelled synthetic demonstration data.
2. Build one generic `ForecastRequest` per canonical signal and use rolling-origin model comparison to select a statistical baseline candidate.
3. Preserve model ID/version, per-signal history SHA-256, target timestamps, and explicit units.
4. Validate the four canonical signals and map them to the dispatch contract without unit guessing.
5. Run a seeded joint battery/diesel schedule search across central and deterministic forecast/grid-outage stress scenarios.
6. Compare candidate policies and expose the hourly schedule vectors, modeled reliability/cost metrics, and customer-service equivalence gate.
7. Export a JSON audit report containing assumptions, provenance, model versions, policy comparison, scenario scope, and the explicit no-device-write boundary.

## Canonical signal contract

| Prediction signal ID | Required unit | Dispatch signal |
| --- | --- | --- |
| `pv_power_kw` | `kW` | `pv_power` |
| `wind_power_kw` | `kW` | `wind_power` |
| `load_kw` | `kW` | `essential_load` |
| `tariff_per_kwh` | caller-declared currency per kWh | `electricity_price` |

All four forecasts must have identical target timestamps. The adapter rejects missing signals, mismatched IDs, unit mismatches, empty horizons, and timestamp misalignment. Tariffs may be negative; physical power signals are non-negative.

## Customer decision and economics guardrails

- The dashboard shows the selected policy, policy comparison, hourly battery/diesel schedule, forecast model quality, provenance and assumptions.
- A modeled cost reduction is displayed only when the optimizer's service-equivalence check passes against the grid-first reference.
- A service mismatch blocks the savings claim; reliability and unmet-load metrics remain visible.
- The search is a bounded seeded heuristic, not a guaranteed global optimum.
- Forecast error envelopes and grid-outage replays are deterministic stress cases without assigned probabilities or calibrated joint coverage.
- Synthetic defaults and uploaded data are clearly labelled. Customer-uploaded data is not independently verified.
- The investment screen is separate from 24-hour scheduling and must use explicit annual customer bills and CAPEX/O&M assumptions; a simulated day is never annualized.

## Stage D acceptance checks

- Generic prediction engine output can execute the complete joint optimizer path.
- Missing canonical signal, invalid unit, and non-aligned horizons fail closed.
- Result metadata preserves per-signal model versions, source-history hashes and target timestamps.
- Joint scheduling requires explicit battery, diesel, grid and diesel availability assumptions.
- The customer-facing page renders model provenance, policy comparisons, schedule outputs and a JSON audit export.
- No device-write action is exposed or authorized.

## Explicit exclusions and Stage E handoff

This is offline decision support, not live dispatch, telemetry ingestion, an authenticated multi-tenant SaaS service, device command execution, a certified safety controller, site validation, or verified customer savings. The optimizer is not a global optimum solver. Stage E remains a separate service/backend/security/identity/telemetry integration stage; its preparation document is `PHASE_E_PREPARATION.md`.
