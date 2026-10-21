# Synthetic dispatch benchmark input

This folder contains deterministic, **synthetic** inputs for a repeatable software integration check.

- `synthetic_dispatch_benchmark.csv`: 168 consecutive hourly rows beginning 2026-01-01 00:00 UTC.
- `actual_surplus_kw`: constructed as `max(0, synthetic solar + synthetic wind - synthetic critical load)`; none of these values are measured site data.
- `forecast_surplus_kw`: a deterministic perturbed version of the synthetic surplus, used to exercise forecast-to-dispatch comparisons.
- `water_demand_m3` and `cooling_demand_kw_th`: illustrative synthetic service demands.

The fixture is designed to exercise the interface and report generation, not to represent Nan'ao, any named island, or a validated renewable profile. Do not cite its metrics as field evidence. The generating assumptions are encoded by the fixed values and deterministic formulas used to create the committed fixture; the exact CSV is the benchmark input of record.
