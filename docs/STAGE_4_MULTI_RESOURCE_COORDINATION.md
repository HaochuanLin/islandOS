# Stage 4 — Multi-resource coordination

## Goal

Stage 4 coordinates forecasted electrical demand and supply with battery, diesel, grid, flexible load, renewable export/curtailment, and optional reverse-osmosis (RO) water production. It prioritizes service feasibility and compares operating cost only after service requirements are considered.

## Implemented coordination path

1. Stage 2 validates site inputs, units, provenance and equipment constraints.
2. Stage 3 emits aligned per-signal forecast bundles with model identity and historical replay evidence.
3. The dispatch adapter maps canonical signals into the physical energy model.
4. When water demand is present, declared RO specific energy, capacity, tank capacity, initial inventory and reserve create an electrical load profile. Missing or infeasible water-service inputs fail closed.
5. The resource optimizer searches battery set-points, diesel commitment and power, flexible-load allocation and grid export within modeled bounds.
6. The same candidate schedule is replayed against nominal forecast, conservative forecast envelope, grid outage, and combined supply/grid stress scenarios. Hard service constraints apply across supplied scenarios.
7. Output preserves source signal IDs, model versions, source digests, scenario outcomes, physical audit results and explicit no-write status.

## Automatic RO policy comparison

The optimize_prediction_resource_schedule function accepts water_schedule_mode='auto' to compare two transparent RO policies:

- just_in_time: produce to serve forecast demand and maintain the declared reserve.
- price_aware: use a bounded tariff look-ahead heuristic to pre-produce in locally cheaper hours while respecting declared RO and tank limits.

Each policy is evaluated with the same energy-system configuration, forecast horizon, random seed, optimizer settings and stress-scenario set. The selected policy is chosen lexicographically by lowest worst-case critical unmet energy, total unmet energy, estimated energy cost, renewable curtailment, then battery throughput. If neither policy can produce a feasible schedule, the request fails closed. The response includes feasibility and comparison metrics for both policies and the selected mode.

## Python usage

```python
result = optimize_prediction_resource_schedule(
    forecast_bundle.results,
    site_energy_config,
    history_start_utc=forecast_bundle.history_start_utc,
    history_end_utc=forecast_bundle.history_end_utc,
    grid_available=grid_availability,
    diesel_available=diesel_availability,
    price_unit="USD/kWh",
    water_service=water_service_spec,
    water_schedule_mode="auto",
    water_lookahead_hours=6,
)
```

## Important limitations

- This compares two RO scheduling heuristics; it is not globally optimal joint water-energy optimization and does not search arbitrary RO set-points.
- Forecast stress cases are deterministic envelopes, not calibrated joint confidence regions or probability-weighted scenarios.
- The evolutionary search is seeded and bounded; it does not guarantee a global optimum.
- Unsupported equipment constraints are rejected rather than silently approximated.
- Economic results are modeled estimates, not measured customer savings.
- This is offline decision support. device_write_authorized remains false; no PLC, inverter, battery, generator or RO controller command is issued.
- Synthetic tests establish software behavior only, not site accuracy, equipment calibration, safety certification or operational readiness.

## Validation

```bash
pytest -q tests/test_stage_f_canonical_workflow.py tests/test_prediction_dispatch_adapter.py
```

The integration test covers aligned multi-signal forecasts, physical battery/diesel scheduling, water-demand-to-RO coupling, comparison of both RO policies, and explicit no-write boundaries.
