# Stage D — Generic forecast-led resource coordination

## Delivered path

Stage D connects the generic prediction engine to the existing joint battery/diesel dispatch optimizer and exposes that end-to-end path in the Streamlit application at `pages/06_Forecast_Led_Joint_Resource_Optimizer.py`.

1. Accept aligned hourly PV, wind, essential-load, tariff, and optional flexible/critical-load/water-demand forecasts from the canonical signal catalog, or use explicitly labelled synthetic demonstration data.
2. Build one generic `ForecastRequest` per canonical signal and use rolling-origin model comparison to select a statistical baseline candidate.
3. Preserve model ID/version, per-signal history SHA-256, target timestamps, and explicit units.
4. Validate the four canonical signals and map them to the dispatch contract without unit guessing.
5. Couple optional water-demand forecasts to a validated RO/tank service replay, convert the resulting RO power to essential electrical demand (and critical load when supplied), and run a seeded joint battery/diesel schedule search across central and deterministic forecast/grid-outage stress scenarios. Optional flexible-load energy is scheduled jointly with battery/diesel within its forecast availability window.
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

## Water and flexible-load integration (first slice)

- The canonical forecast adapter accepts optional flexible_load_kw and critical_load_kw signals. Flexible-load forecast energy is conserved over its declared non-zero availability window and scheduled jointly with battery/diesel.
- The water adapter validates RO specific energy, rated production, tank capacity, initial inventory, and reserve; it replays the empirical upper water-demand planning bound and converts feasible RO production into kW.
- RO demand is added to essential load and to the critical subset when one is supplied. A water forecast without an explicit WaterServiceSpec fails closed.
- RO production currently follows reserve-constrained just-in-time operation. It is **not** price-optimized, tank trajectory is not a decision variable, and detailed RO process constraints are not represented.
- The heuristic is not globally optimal; forecast upper bounds are not calibrated probability intervals.

See `docs/STAGE_D_WATER_FLEX_COORDINATION.md` for the interface and limitations.

## Explicit exclusions and Stage E handoff

This remains offline decision support, not live dispatch, a complete water-energy co-optimizer, telemetry ingestion, a production multi-tenant SaaS service, device command execution, a certified safety controller, site validation, or verified customer savings. The optimizer is not a global optimum solver. Stage E remains a separate service/backend/security/identity/telemetry integration stage; its preparation document is `PHASE_E_PREPARATION.md`.
