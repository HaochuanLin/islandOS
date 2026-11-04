# Reproducible Integrated Microgrid Demo

Run from the repository root:

```bash
python tools/run_integrated_microgrid_demo.py --hours 168 --seed 20261104
```

The command compares two paired policies on the same deterministic synthetic PV, wind, essential-load, water-demand, grid-availability, tariff, and emissions inputs:

- **No-RO baseline:** the integrated model serves essential electricity demand and operates the battery/grid/diesel layers; no flexible RO load is requested.
- **Renewable-only RO flexible load:** requests the configured RO rating each hour; the physical model serves it only from renewable power remaining after essential electricity demand and clips production to water-tank headroom.

Outputs under `build/integrated-microgrid-demo/`:

- `benchmark_report.json`: seed, time horizon, provenance label, assumptions, policy descriptions, and aggregate metrics for both cases.
- `hourly_comparison.csv`: hourly input signals and the flexible-load case's energy, water, and service metrics.

The demo is deliberately a transparent policy comparison, not an optimizer benchmark. It does not forecast any input series and does not claim that RO always improves cost or reliability. A hash or fixed seed makes the synthetic run reproducible; it does not turn synthetic inputs into measurements.

Regression tests:

```bash
python -m unittest tests.test_microgrid_model tests.test_integrated_microgrid_demo -v
```
