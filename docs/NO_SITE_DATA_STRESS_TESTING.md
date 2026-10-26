# IslandOS stress testing without site data

## Objective

IslandOS must make measurable engineering progress even when no measured island telemetry exists. This suite does that by testing declared assumptions, deterministic scenario transformations, forecast-error sensitivity, resource scarcity, demand shocks, and fail-closed behavior. It does **not** fabricate real-world evidence: all cases are explicitly synthetic software probes.

## Run

From the repository root:

```bash
python -m experiments.run_synthetic_stress_suite --hours 48
python -m experiments.run_synthetic_stress_suite --hours 168 --output build/stress-168h/report.json
```

The report defaults to `build/synthetic-stress-suite/report.json` and includes ten cases:

| Case | Purpose |
|---|---|
| `baseline_synthetic` | Deterministic reference profile |
| `forecast_overestimate_50pct` | Stress planning with an optimistic renewable forecast |
| `forecast_underestimate_50pct` | Stress planning with a pessimistic renewable forecast |
| `renewable_drought` | Zero renewable surplus throughout the profile |
| `water_demand_spike` | Double actual and forecast water demand |
| `cooling_demand_spike` | Double cooling demand |
| `compound_adverse` | Lower actual surplus, optimistic surplus forecast, and higher demand |
| `invalid_telemetry` | Verify fail-closed response to a false telemetry-quality flag |
| `unhealthy_interlocks` | Verify fail-closed response to an unhealthy interlock flag |
| `operator_stop` | Verify fail-closed response to a stop request |

Each case records its input digest, duration, water/cooling unmet demand, constraint-violation hours, remaining surplus, final inventories, and ON/OFF/HOLD counts. The suite digest is derived from the ordered result summaries. Determinism makes regression comparisons possible; the hash does not authenticate measurements.

## How to interpret results

- Compare forecast perturbations against the same underlying actual profile to observe sensitivity to planning error.
- Treat unmet water/cooling demand and constraint violations as adverse outcomes to investigate, not as a single score that can hide trade-offs.
- Verify all safety-flag cases return HOLD for every simulated hour.
- Run short profiles for quick regression tests and longer profiles to expose inventory drift and repeated scarcity.
- Add a new scenario whenever a discovered failure mode can be stated as a deterministic, testable assumption.

## Limits and next improvements

The matrix is hand-designed and not a probability distribution of real island weather or consumption. It cannot estimate real forecast error distributions, prove a forecast model is calibrated, or establish field performance. The underlying dispatcher remains simplified; no scenario substitutes for equipment curves, reserve policies, electrical protection, thermal losses, maintenance states, or site-approved interlocks.

Without site data, the next defensible improvements are stronger property/invariant tests, randomized but seeded parameter sweeps, explicit sensitivity reports, comparisons against simple baseline policies, and transparent model uncertainty. Any ML model trained on generated data must be labeled synthetic-trained and should not be promoted as site-accurate. A language model may help explain results or propose experiments, but deterministic validators and dispatch constraints must remain authoritative.
